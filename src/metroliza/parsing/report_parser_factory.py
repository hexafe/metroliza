"""Parser plugin registry and deterministic runtime resolver.

Parser discovery and selection are owned by :mod:`metroliza.parsing`.  The former
``metroliza.reports.report_parser_factory`` path remains a module-identity compatibility alias.

This module keeps compatibility with both:
- new registration: ``register_parser(ParserClass)``
- legacy registration: ``register_parser(format_id, ParserClass, detector=..., manifest=...)``
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
from importlib import metadata as importlib_metadata
import importlib.util
import inspect
import logging
from pathlib import Path
import re
import sys
from threading import Event, RLock
from typing import Callable, Literal, Type

from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.shared.env_utils import env_bool
from metroliza.parsing import parser_plugin_paths
from metroliza.parsing.parser_plugin_contracts import (
    BaseReportParserPlugin,
    PluginManifest,
    ProbeContext,
    ProbeOutcome,
    ProbeResult,
    infer_source_format,
)
from metroliza.parsing.source_inspection import SourceInspectionContext


ParserType = Type[BaseReportParserPlugin]
DetectorType = Callable[..., ProbeResult]
ParserOrigin = Literal[
    "builtin",
    "manual",
    "approved_profile",
    "python_path",
    "entry_point",
]
ExternalPluginConfigSignature = tuple[object, ...]


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
    registry_generation_id: int | None = None
    registration_origins: tuple[tuple[str, str], ...] = ()
    registry_load_errors: tuple[str, ...] = ()
    ambiguous_plugin_ids: tuple[str, ...] = ()


class UnsupportedReportFormatError(ValueError):
    """Raised when no registered parser semantically accepts a report source."""

    def __init__(self, diagnostics: ResolverDiagnostics):
        self.diagnostics = diagnostics
        self.source_path = diagnostics.source_path
        super().__init__(
            "Unsupported report format: "
            f"{diagnostics.source_format or 'unknown'} ({diagnostics.source_path})"
        )


class ParserInspectionError(ValueError):
    """Raised when parser compatibility could not be determined reliably."""

    def __init__(self, diagnostics: ResolverDiagnostics):
        self.diagnostics = diagnostics
        self.source_path = diagnostics.source_path
        super().__init__(
            "Report content inspection failed: "
            f"{diagnostics.source_format or 'unknown'} ({diagnostics.source_path})"
        )


class ParserAmbiguityError(ValueError):
    """Raised when multiple parsers have the same meaningful evidence rank."""

    def __init__(self, diagnostics: ResolverDiagnostics, plugin_ids: tuple[str, ...]):
        self.diagnostics = diagnostics
        self.plugin_ids = plugin_ids
        self.source_path = diagnostics.source_path
        super().__init__(
            "Ambiguous report parser match for "
            f"{diagnostics.source_path}: {', '.join(plugin_ids)}"
        )


class ParserApprovalMismatchError(ValueError):
    """Raised when parser resolution no longer matches reviewed approval."""

    def __init__(
        self,
        diagnostics: ResolverDiagnostics,
        *,
        expected_plugin_id: str | None,
        expected_registry_generation_id: int | None,
    ) -> None:
        self.diagnostics = diagnostics
        self.expected_plugin_id = expected_plugin_id
        self.expected_registry_generation_id = expected_registry_generation_id
        self.resolved_plugin_id = (
            diagnostics.selected.plugin_id
            if diagnostics.selected is not None
            else None
        )
        self.resolved_registry_generation_id = diagnostics.registry_generation_id
        super().__init__(
            "Parser approval changed after review: "
            f"expected plugin={expected_plugin_id!r}, "
            f"generation={expected_registry_generation_id!r}; "
            f"resolved plugin={self.resolved_plugin_id!r}, "
            f"generation={self.resolved_registry_generation_id!r}"
        )


class ParserRegistrationError(ValueError):
    """Base error for invalid parser registry mutations."""


class DuplicateParserRegistrationError(ParserRegistrationError):
    """Raised when a parser id is registered twice without explicit replacement."""


class ReservedParserPluginError(ParserRegistrationError):
    """Raised when external code attempts to register the built-in CMM id."""


_PLUGIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


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
class ParserRegistration:
    """One immutable parser registration in a published registry generation."""

    plugin_id: str
    parser_cls: ParserType
    manifest: PluginManifest
    detector: DetectorType | None
    origin: ParserOrigin
    origin_ref: str | None = None


@dataclass(frozen=True)
class ParserResolutionEvidence:
    """Exact resolver result used to construct one parser instance."""

    plugin_id: str
    registry_generation_id: int
    registration: ParserRegistration = field(compare=False, repr=False)
    diagnostics: ResolverDiagnostics = field(compare=False, repr=False)


@dataclass(frozen=True)
class RegistrySnapshot:
    """Immutable, coherent view of all parsers available to one operation."""

    generation_id: int
    registrations: tuple[ParserRegistration, ...]
    load_errors: tuple[str, ...] = ()


PARSER_MAP: dict[str, ParserType] = {}
PARSER_MANIFESTS: dict[str, PluginManifest] = {}
PARSER_DETECTORS: dict[str, DetectorType] = {}
PROBE_RESULT_CACHE_MAX_ENTRIES = 2048
PROBE_RESULT_CACHE: OrderedDict[
    tuple[str, str, tuple[object, ...], int, int, int],
    ProbeResult,
] = OrderedDict()
_PARSER_REGISTRY_LOCK = RLock()
_EXTERNAL_PLUGIN_REFRESH_LOCK = RLock()
_PROBE_RESULT_CACHE_LOCK = RLock()
_PROBE_RESULT_CACHE_INFLIGHT: dict[
    tuple[int, tuple[str, str, tuple[object, ...], int, int, int]],
    Event,
] = {}
_PROBE_RESULT_CACHE_EPOCH = 0
_EXTERNAL_PLUGINS_LOADED = False
_EXTERNAL_PLUGIN_CONFIG_SIGNATURE: ExternalPluginConfigSignature | None = None
_EXTERNAL_PLUGIN_ENTRY_POINTS: tuple[object, ...] | None = None
_EXTERNAL_PLUGIN_MODULE_COUNTER = 0
_EXTERNAL_PLUGIN_LOADER_EPOCH = 0
_EXTERNAL_PLUGIN_MODULE_CACHE: dict[tuple[str, str], tuple[str, object]] = {}
_ENTRY_POINT_LOAD_CACHE: dict[tuple[str, str, str], object] = {}
_MANUAL_REGISTRATIONS: OrderedDict[str, ParserRegistration] = OrderedDict()
_DIRECT_EXTERNAL_REGISTRATIONS: OrderedDict[str, ParserRegistration] = OrderedDict()
_REGISTRY_SNAPSHOT = RegistrySnapshot(generation_id=0, registrations=())

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
            outcome=ProbeOutcome.INSPECTION_ERROR,
        )

    normalized_confidence = _clamp_confidence(raw_result.confidence)
    reasons = _coerce_string_tuple(raw_result.reasons)
    warnings = list(_coerce_string_tuple(raw_result.warnings))
    if normalized_confidence != raw_result.confidence:
        warnings.append(f"confidence_clamped_from_{raw_result.confidence}_to_{normalized_confidence}")
    if raw_result.plugin_id != plugin_id:
        warnings.append(f"plugin_id_normalized_from_{raw_result.plugin_id}")

    outcome = raw_result.outcome
    if (outcome is ProbeOutcome.MATCH) != bool(raw_result.can_parse):
        outcome = ProbeOutcome.INSPECTION_ERROR
        reasons = (*reasons, "invalid_probe_contract")
        warnings.append(
            "ProbeOutcome.MATCH must agree with the legacy can_parse field"
        )
    if outcome is ProbeOutcome.NO_MATCH and any(
        reason == "content_inspection_failed" or reason.endswith("_exception")
        for reason in reasons
    ):
        outcome = ProbeOutcome.INSPECTION_ERROR
    if outcome is ProbeOutcome.MATCH and raw_result.semantic_row_count == 0:
        outcome = ProbeOutcome.INSPECTION_ERROR
        reasons = (*reasons, "semantic_match_without_rows")
        warnings.append("MATCH outcomes with explicit semantic_row_count=0 are invalid")
    can_parse = outcome is ProbeOutcome.MATCH

    return ProbeResult(
        plugin_id=plugin_id,
        can_parse=can_parse,
        confidence=normalized_confidence,
        matched_template_id=raw_result.matched_template_id,
        reasons=reasons,
        warnings=tuple(warnings),
        outcome=outcome,
        semantic_row_count=raw_result.semantic_row_count,
    )


def _maps_match_snapshot_locked(snapshot: RegistrySnapshot) -> bool:
    if tuple(PARSER_MAP) != tuple(registration.plugin_id for registration in snapshot.registrations):
        return False
    for registration in snapshot.registrations:
        if PARSER_MAP.get(registration.plugin_id) is not registration.parser_cls:
            return False
        if PARSER_MANIFESTS.get(registration.plugin_id) != registration.manifest:
            return False
        if PARSER_DETECTORS.get(registration.plugin_id) is not registration.detector:
            return False
    return set(PARSER_MANIFESTS) == set(PARSER_MAP) and set(PARSER_DETECTORS).issubset(PARSER_MAP)


def _publish_registry_locked(
    registrations: tuple[ParserRegistration, ...],
    *,
    load_errors: tuple[str, ...] = (),
) -> RegistrySnapshot:
    """Publish one complete generation and its compatibility maps under one lock."""

    global _REGISTRY_SNAPSHOT

    snapshot = RegistrySnapshot(
        generation_id=_REGISTRY_SNAPSHOT.generation_id + 1,
        registrations=registrations,
        load_errors=load_errors,
    )
    PARSER_MAP.clear()
    PARSER_MANIFESTS.clear()
    PARSER_DETECTORS.clear()
    for registration in registrations:
        PARSER_MAP[registration.plugin_id] = registration.parser_cls
        PARSER_MANIFESTS[registration.plugin_id] = registration.manifest
        if registration.detector is not None:
            PARSER_DETECTORS[registration.plugin_id] = registration.detector
    _REGISTRY_SNAPSHOT = snapshot
    reset_probe_cache()
    return snapshot


def _registration_matches_maps(registration: ParserRegistration) -> bool:
    return (
        PARSER_MAP.get(registration.plugin_id) is registration.parser_cls
        and PARSER_MANIFESTS.get(registration.plugin_id) == registration.manifest
        and PARSER_DETECTORS.get(registration.plugin_id) is registration.detector
    )


def _synchronize_compatibility_maps_locked() -> RegistrySnapshot:
    """Fold legacy direct map mutations into one validated immutable snapshot.

    The dictionaries remain public compatibility views.  Treating a direct edit as
    a manual registration keeps old integrations working while all production
    readers still consume one coherent snapshot.
    """

    global _MANUAL_REGISTRATIONS, _DIRECT_EXTERNAL_REGISTRATIONS

    if _maps_match_snapshot_locked(_REGISTRY_SNAPSHOT):
        return _REGISTRY_SNAPSHOT

    previous = {
        registration.plugin_id: registration
        for registration in _REGISTRY_SNAPSHOT.registrations
    }
    registrations: list[ParserRegistration] = []
    errors: list[str] = list(_REGISTRY_SNAPSHOT.load_errors)
    for plugin_id, parser_cls in tuple(PARSER_MAP.items()):
        manifest = PARSER_MANIFESTS.get(plugin_id)
        detector = PARSER_DETECTORS.get(plugin_id)
        prior = previous.get(plugin_id)
        if prior is not None and (
            prior.parser_cls is parser_cls
            and prior.manifest == manifest
            and prior.detector is detector
        ):
            registration = prior
        else:
            is_builtin_cmm = (
                plugin_id == "cmm"
                and parser_cls is CMMReportParser
                and manifest == CMMReportParser.manifest
            )
            registration = ParserRegistration(
                plugin_id=plugin_id,
                parser_cls=parser_cls,
                manifest=manifest,
                detector=detector,
                origin="builtin" if is_builtin_cmm else "manual",
                origin_ref="metroliza" if is_builtin_cmm else "compatibility-map",
            )
        try:
            _validate_parser_registration(
                registration.plugin_id,
                registration.parser_cls,
                registration.manifest,
                registration.detector,
            )
        except Exception as exc:
            errors.append(f"compatibility map {plugin_id!r}: {exc}")
            continue
        registrations.append(registration)

    live_ids = {registration.plugin_id for registration in registrations}
    _MANUAL_REGISTRATIONS = OrderedDict(
        (registration.plugin_id, registration)
        for registration in registrations
        if registration.origin == "manual"
    )
    _DIRECT_EXTERNAL_REGISTRATIONS = OrderedDict(
        (plugin_id, registration)
        for plugin_id, registration in _DIRECT_EXTERNAL_REGISTRATIONS.items()
        if plugin_id in live_ids and _registration_matches_maps(registration)
    )
    return _publish_registry_locked(tuple(registrations), load_errors=tuple(errors))


def get_registry_snapshot(*, refresh: bool = True) -> RegistrySnapshot:
    """Return the authoritative immutable parser-registry generation.

    ``refresh=True`` checks the current profile/path/entry-point configuration and
    atomically publishes a new generation only when that configuration changed.
    """

    if refresh:
        _ensure_external_plugins_loaded_once()
    with _PARSER_REGISTRY_LOCK:
        return _synchronize_compatibility_maps_locked()


def list_plugins() -> tuple[PluginManifest, ...]:
    """Return manifests from one authoritative registry generation."""

    return tuple(
        registration.manifest
        for registration in get_registry_snapshot().registrations
    )


def _registry_snapshot() -> tuple[ParserRegistration, ...]:
    """Compatibility helper returning registrations without triggering a refresh."""

    return get_registry_snapshot(refresh=False).registrations


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

    with _EXTERNAL_PLUGIN_REFRESH_LOCK:
        with _PARSER_REGISTRY_LOCK:
            _EXTERNAL_PLUGINS_LOADED = False
            _EXTERNAL_PLUGIN_CONFIG_SIGNATURE = None
            _EXTERNAL_PLUGIN_ENTRY_POINTS = None
            _EXTERNAL_PLUGIN_LOADER_EPOCH += 1


def _unregister_parser(plugin_id: str) -> None:
    with _EXTERNAL_PLUGIN_REFRESH_LOCK:
        with _PARSER_REGISTRY_LOCK:
            snapshot = _synchronize_compatibility_maps_locked()
            registrations = tuple(
                registration
                for registration in snapshot.registrations
                if registration.plugin_id != plugin_id
            )
            _MANUAL_REGISTRATIONS.pop(plugin_id, None)
            _DIRECT_EXTERNAL_REGISTRATIONS.pop(plugin_id, None)
            _publish_registry_locked(registrations, load_errors=snapshot.load_errors)


def _unregister_declarative_profile_parsers() -> None:
    with _EXTERNAL_PLUGIN_REFRESH_LOCK:
        with _PARSER_REGISTRY_LOCK:
            snapshot = _synchronize_compatibility_maps_locked()
            registrations = tuple(
                registration
                for registration in snapshot.registrations
                if registration.origin != "approved_profile"
            )
            if registrations != snapshot.registrations:
                _publish_registry_locked(registrations, load_errors=snapshot.load_errors)


def plugins_for_format(source_format: str) -> tuple[ParserType, ...]:
    """Return plugins compatible with a source format."""

    return tuple(
        registration.parser_cls
        for registration in get_registry_snapshot().registrations
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
            outcome=ProbeOutcome.INSPECTION_ERROR,
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


def _probe_result_has_inspection_failure(candidate: ProbeResult) -> bool:
    return candidate.outcome is ProbeOutcome.INSPECTION_ERROR or any(
        reason == "content_inspection_failed" or reason.endswith("_exception")
        for reason in candidate.reasons
    )


def _probe_with_cache(
    plugin_id: str,
    parser_cls: ParserType,
    normalized_path: str,
    probe_context: ProbeContext,
    detector: DetectorType | None = None,
    *,
    generation_id: int | None = None,
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
    if generation_id is None:
        with _PARSER_REGISTRY_LOCK:
            generation_id = _REGISTRY_SNAPSHOT.generation_id
    cache_key = (
        plugin_id,
        normalized_path,
        cache_identity,
        id(parser_cls),
        id(detector),
        generation_id,
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
            if (
                cache_epoch == _PROBE_RESULT_CACHE_EPOCH
                and result.outcome is not ProbeOutcome.INSPECTION_ERROR
            ):
                PROBE_RESULT_CACHE[cache_key] = result
                PROBE_RESULT_CACHE.move_to_end(cache_key)
                while len(PROBE_RESULT_CACHE) > PROBE_RESULT_CACHE_MAX_ENTRIES:
                    PROBE_RESULT_CACHE.popitem(last=False)
        return result
    finally:
        with _PROBE_RESULT_CACHE_LOCK:
            completed = _PROBE_RESULT_CACHE_INFLIGHT.pop(inflight_key, inflight)
            completed.set()


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_external_module(candidate: Path) -> tuple[str, object]:
    """Import one plugin module once per resolved path and content digest."""

    resolved = str(candidate.resolve(strict=False))
    content_sha256 = _sha256_file(candidate)
    cache_key = (resolved, content_sha256)
    cached = _EXTERNAL_PLUGIN_MODULE_CACHE.get(cache_key)
    if cached is not None:
        module_name, module = cached
        sys.modules[module_name] = module
        return cached

    module_name = _next_external_module_name()
    spec = importlib.util.spec_from_file_location(module_name, candidate)
    if spec is None or spec.loader is None:
        raise ImportError("failed to create import spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    _EXTERNAL_PLUGIN_MODULE_CACHE[cache_key] = (module_name, module)
    return module_name, module


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
    return sorted(
        plugin_classes,
        key=lambda parser_cls: (
            getattr(getattr(parser_cls, "manifest", None), "plugin_id", ""),
            parser_cls.__name__,
        ),
    )


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


def _entry_point_cache_key(entry_point: object) -> tuple[str, str, str]:
    distribution = getattr(entry_point, "dist", None)
    distribution_name = str(getattr(distribution, "name", ""))
    distribution_version = str(getattr(distribution, "version", ""))
    distribution_ref = f"{distribution_name}=={distribution_version}"
    return (
        str(getattr(entry_point, "name", "")),
        str(getattr(entry_point, "value", repr(entry_point))),
        distribution_ref,
    )


def _load_entry_point(entry_point: object):
    cache_key = _entry_point_cache_key(entry_point)
    if cache_key not in _ENTRY_POINT_LOAD_CACHE:
        _ENTRY_POINT_LOAD_CACHE[cache_key] = entry_point.load()
    return _ENTRY_POINT_LOAD_CACHE[cache_key]


def _registration_from_parser_class(
    parser_cls: ParserType,
    *,
    origin: ParserOrigin,
    origin_ref: str | None,
    plugin_id: str | None = None,
    detector: DetectorType | None = None,
) -> ParserRegistration:
    manifest = getattr(parser_cls, "manifest", None)
    if plugin_id is None:
        plugin_id = (
            manifest.plugin_id
            if isinstance(manifest, PluginManifest)
            else _infer_plugin_id_from_parser_cls(parser_cls)
        )
    if manifest is None:
        manifest = _default_manifest(plugin_id, parser_cls)
    registration = ParserRegistration(
        plugin_id=plugin_id,
        parser_cls=parser_cls,
        manifest=manifest,
        detector=detector,
        origin=origin,
        origin_ref=origin_ref,
    )
    _validate_parser_registration(
        registration.plugin_id,
        registration.parser_cls,
        registration.manifest,
        registration.detector,
    )
    return registration


def _append_registration(
    registrations: list[ParserRegistration],
    registration: ParserRegistration,
    errors: list[str],
) -> bool:
    """Append a valid non-colliding registration in deterministic source order."""

    try:
        _validate_parser_registration(
            registration.plugin_id,
            registration.parser_cls,
            registration.manifest,
            registration.detector,
        )
    except Exception as exc:
        errors.append(f"{registration.origin} {registration.origin_ref or '<unknown>'}: {exc}")
        return False

    existing = next(
        (
            candidate
            for candidate in registrations
            if candidate.plugin_id == registration.plugin_id
        ),
        None,
    )
    if existing == registration:
        return True
    if existing is not None:
        errors.append(
            f"{registration.origin} {registration.origin_ref or '<unknown>'}: plugin id "
            f"{registration.plugin_id!r} conflicts with {existing.origin} "
            f"{existing.origin_ref or existing.plugin_id}"
        )
        return False
    registrations.append(registration)
    return True


def _collect_python_path_registrations(
    path_entries: tuple[str, ...],
    *,
    disabled_ids: frozenset[str],
) -> tuple[tuple[ParserRegistration, ...], ExternalPluginLoadResult]:
    registrations: list[ParserRegistration] = []
    loaded_modules: list[str] = []
    skipped_paths: list[str] = []
    errors: list[str] = []

    for entry in path_entries:
        candidates = _iter_external_plugin_candidate_files(entry)
        if not candidates:
            skipped_paths.append(entry)
            continue
        for candidate in candidates:
            try:
                module_name, module = _load_external_module(candidate)
                loaded_modules.append(module_name)
            except Exception as exc:  # pragma: no cover - defensive hardening
                errors.append(f"{candidate}: {exc}")
                continue

            for parser_cls in _discover_plugin_classes_in_module(module):
                try:
                    registration = _registration_from_parser_class(
                        parser_cls,
                        origin="python_path",
                        origin_ref=str(candidate.resolve(strict=False)),
                    )
                except Exception as exc:
                    errors.append(f"{candidate}: {exc}")
                    continue
                if registration.plugin_id in disabled_ids:
                    continue
                registrations.append(registration)

    return (
        tuple(registrations),
        ExternalPluginLoadResult(
            loaded_plugin_ids=tuple(registration.plugin_id for registration in registrations),
            loaded_modules=tuple(loaded_modules),
            skipped_paths=tuple(skipped_paths),
            errors=tuple(errors),
        ),
    )


def _collect_entry_point_registrations(
    entry_points: tuple[object, ...],
    *,
    disabled_ids: frozenset[str],
) -> tuple[tuple[ParserRegistration, ...], ExternalPluginLoadResult]:
    registrations: list[ParserRegistration] = []
    loaded_entry_points: list[str] = []
    errors: list[str] = []
    ordered_entry_points = sorted(entry_points, key=_entry_point_cache_key)

    for entry_point in ordered_entry_points:
        entry_point_name = str(getattr(entry_point, "name", "<unnamed>"))
        try:
            loaded = _load_entry_point(entry_point)
        except Exception as exc:  # pragma: no cover - defensive hardening
            errors.append(f"entry-point {entry_point_name}: {exc}")
            continue
        parser_classes = loaded if isinstance(loaded, (list, tuple)) else (loaded,)
        for parser_cls in sorted(
            parser_classes,
            key=lambda value: (
                getattr(getattr(value, "manifest", None), "plugin_id", ""),
                getattr(value, "__name__", ""),
            ),
        ):
            try:
                registration = _registration_from_parser_class(
                    parser_cls,
                    origin="entry_point",
                    origin_ref=entry_point_name,
                )
            except Exception as exc:
                errors.append(f"entry-point {entry_point_name}: {exc}")
                continue
            if registration.plugin_id in disabled_ids:
                continue
            registrations.append(registration)
        loaded_entry_points.append(entry_point_name)

    return (
        tuple(registrations),
        ExternalPluginLoadResult(
            loaded_plugin_ids=tuple(registration.plugin_id for registration in registrations),
            loaded_entry_points=tuple(loaded_entry_points),
            errors=tuple(errors),
        ),
    )


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

    with _EXTERNAL_PLUGIN_REFRESH_LOCK:
        disabled_ids = parser_plugin_paths.disabled_plugin_ids()
        if paths is None:
            path_entries = parser_plugin_paths.configured_external_plugin_path_entries()
        elif isinstance(paths, str):
            path_entries = parser_plugin_paths.split_external_plugin_paths(paths)
        else:
            path_entries = tuple(entry for entry in paths if entry)
        entry_points_to_load = (
            entry_points
            if entry_points is not None
            else _discover_external_plugin_entry_points(force_refresh=True)
        )

        path_registrations, path_result = _collect_python_path_registrations(
            tuple(path_entries),
            disabled_ids=disabled_ids,
        )
        entry_registrations, entry_result = _collect_entry_point_registrations(
            tuple(entry_points_to_load),
            disabled_ids=disabled_ids,
        )
        errors = [*path_result.errors, *entry_result.errors]
        accepted_ids: list[str] = []

        retain_direct = paths is not None or entry_points is not None
        with _PARSER_REGISTRY_LOCK:
            snapshot = _synchronize_compatibility_maps_locked()
            registrations = list(snapshot.registrations)
            for registration in (*path_registrations, *entry_registrations):
                existing = next(
                    (
                        candidate
                        for candidate in registrations
                        if candidate.plugin_id == registration.plugin_id
                    ),
                    None,
                )
                if existing == registration:
                    accepted_ids.append(registration.plugin_id)
                    if retain_direct:
                        _DIRECT_EXTERNAL_REGISTRATIONS[registration.plugin_id] = registration
                    continue
                if _append_registration(registrations, registration, errors):
                    accepted_ids.append(registration.plugin_id)
                    if retain_direct:
                        _DIRECT_EXTERNAL_REGISTRATIONS[registration.plugin_id] = registration
            if accepted_ids or errors:
                _publish_registry_locked(tuple(registrations), load_errors=tuple(errors))

        return ExternalPluginLoadResult(
            loaded_plugin_ids=tuple(accepted_ids),
            loaded_modules=path_result.loaded_modules,
            loaded_entry_points=entry_result.loaded_entry_points,
            skipped_paths=path_result.skipped_paths,
            errors=tuple(errors),
        )


def _load_approved_declarative_profiles(
) -> tuple[ExternalPluginLoadResult, tuple[ParserRegistration, ...]]:
    """Load approved data-only parser profiles from the self-service store."""

    try:
        from metroliza.parsing.declarative_parser_profiles import load_approved_profile_parsers
    except Exception as exc:  # pragma: no cover - import hardening
        return (
            ExternalPluginLoadResult(
                errors=(f"declarative profile loader unavailable: {exc}",),
            ),
            (),
        )

    loaded_profile_ids: list[str] = []
    errors: list[str] = []
    profiles, profile_errors = load_approved_profile_parsers()
    errors.extend(profile_errors)
    registrations: list[ParserRegistration] = []
    disabled_ids = parser_plugin_paths.disabled_plugin_ids()
    for plugin_id, parser_cls in sorted(profiles, key=lambda item: item[0]):
        try:
            registration = _registration_from_parser_class(
                parser_cls,
                plugin_id=plugin_id,
                origin="approved_profile",
                origin_ref=str(getattr(parser_cls, "profile_origin_path", "")) or None,
            )
        except Exception as exc:
            errors.append(f"declarative profile {plugin_id}: {exc}")
            continue
        if registration.plugin_id in disabled_ids:
            continue
        registrations.append(registration)
        loaded_profile_ids.append(plugin_id)

    return ExternalPluginLoadResult(
        loaded_plugin_ids=tuple(loaded_profile_ids),
        loaded_profile_ids=tuple(loaded_profile_ids),
        errors=tuple(errors),
    ), tuple(registrations)


def _current_declarative_profile_signature() -> tuple[tuple[str, str, str], ...]:
    try:
        from metroliza.parsing.declarative_parser_profiles import profile_store_signature
    except Exception as exc:  # pragma: no cover - import hardening
        return (("profile_loader_unavailable", type(exc).__name__, str(exc)),)
    try:
        return profile_store_signature()
    except Exception as exc:  # pragma: no cover - filesystem hardening
        return (("profile_signature_unavailable", type(exc).__name__, str(exc)),)


def _current_external_path_signature(
    path_entries: tuple[str, ...],
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    signature: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for entry in path_entries:
        candidate_signatures: list[tuple[str, str]] = []
        try:
            candidates = _iter_external_plugin_candidate_files(entry)
        except Exception as exc:  # pragma: no cover - filesystem hardening
            candidate_signatures.append((entry, f"error:{type(exc).__name__}:{exc}"))
        else:
            for candidate in candidates:
                try:
                    digest = _sha256_file(candidate)
                except Exception as exc:  # pragma: no cover - filesystem hardening
                    digest = f"error:{type(exc).__name__}:{exc}"
                candidate_signatures.append((str(candidate.resolve(strict=False)), digest))
        signature.append((entry, tuple(candidate_signatures)))
    return tuple(signature)


def _builtin_cmm_registration() -> ParserRegistration:
    return ParserRegistration(
        plugin_id="cmm",
        parser_cls=CMMReportParser,
        manifest=CMMReportParser.manifest,
        detector=_default_cmm_detector,
        origin="builtin",
        origin_ref="metroliza",
    )


def _base_registrations_for_refresh() -> tuple[ParserRegistration, ...]:
    """Return built-in, manual, and explicitly loaded registrations in precedence order."""

    with _PARSER_REGISTRY_LOCK:
        _synchronize_compatibility_maps_locked()
        disabled_ids = parser_plugin_paths.disabled_plugin_ids()
        return (
            _builtin_cmm_registration(),
            *(
                registration
                for plugin_id, registration in _MANUAL_REGISTRATIONS.items()
                if plugin_id != "cmm"
            ),
            *(
                registration
                for plugin_id, registration in _DIRECT_EXTERNAL_REGISTRATIONS.items()
                if plugin_id != "cmm" and plugin_id not in disabled_ids
            ),
        )


def _ensure_external_plugins_loaded_once() -> None:
    """Refresh external registrations once per coherent configuration generation."""

    global _EXTERNAL_PLUGINS_LOADED, _EXTERNAL_PLUGIN_CONFIG_SIGNATURE

    with _EXTERNAL_PLUGIN_REFRESH_LOCK:
        with _PARSER_REGISTRY_LOCK:
            was_loaded = _EXTERNAL_PLUGINS_LOADED
            current = _synchronize_compatibility_maps_locked()
            builtin_present = any(
                registration.plugin_id == "cmm"
                and registration.origin == "builtin"
                and registration.parser_cls is CMMReportParser
                for registration in current.registrations
            )

        path_entries = parser_plugin_paths.configured_external_plugin_path_entries()
        entry_points = _discover_external_plugin_entry_points(force_refresh=not was_loaded)
        entry_point_signature = tuple(
            _entry_point_cache_key(entry_point)
            for entry_point in sorted(entry_points, key=_entry_point_cache_key)
        )
        profile_signature = _current_declarative_profile_signature()
        disabled_ids = parser_plugin_paths.disabled_plugin_ids()
        config_signature: ExternalPluginConfigSignature = (
            path_entries,
            _current_external_path_signature(path_entries),
            entry_point_signature,
            profile_signature,
            tuple(sorted(disabled_ids)),
        )

        with _PARSER_REGISTRY_LOCK:
            if (
                _EXTERNAL_PLUGINS_LOADED
                and _EXTERNAL_PLUGIN_CONFIG_SIGNATURE == config_signature
                and builtin_present
            ):
                return

        profile_load_result, profile_registrations = _load_approved_declarative_profiles()
        path_registrations, path_load_result = _collect_python_path_registrations(
            path_entries,
            disabled_ids=disabled_ids,
        )
        entry_registrations, entry_load_result = _collect_entry_point_registrations(
            entry_points,
            disabled_ids=disabled_ids,
        )
        errors = [
            *profile_load_result.errors,
            *path_load_result.errors,
            *entry_load_result.errors,
        ]
        registrations: list[ParserRegistration] = []
        for registration in (
            *_base_registrations_for_refresh(),
            *profile_registrations,
            *path_registrations,
            *entry_registrations,
        ):
            _append_registration(registrations, registration, errors)

        for error in errors:
            logger.warning("External parser plugin load issue: %s", error)

        with _PARSER_REGISTRY_LOCK:
            _publish_registry_locked(tuple(registrations), load_errors=tuple(errors))
            _EXTERNAL_PLUGINS_LOADED = True
            _EXTERNAL_PLUGIN_CONFIG_SIGNATURE = config_signature


def _resolve_parser_with_registration(
    file_path: str | Path,
    *,
    source_inspection: SourceInspectionContext | None = None,
) -> tuple[ResolverDiagnostics, ParserRegistration | None]:
    """Resolve one parser from a coherent registry snapshot."""

    snapshot = get_registry_snapshot()
    registrations = snapshot.registrations
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
                generation_id=snapshot.generation_id,
            )
        )

    diagnostic_metadata = {
        "registry_generation_id": snapshot.generation_id,
        "registration_origins": tuple(
            (registration.plugin_id, registration.origin)
            for registration in registrations
        ),
        "registry_load_errors": snapshot.load_errors,
    }

    minimum_confidence = _minimum_confidence_for_selection()
    parseable = [
        candidate
        for candidate in candidates
        if candidate.outcome is ProbeOutcome.MATCH
        and candidate.can_parse
        and candidate.confidence >= minimum_confidence
    ]
    if not parseable:
        rejected_reason = "no_plugin_can_parse"
        if any(_probe_result_has_inspection_failure(c) for c in candidates):
            rejected_reason = "parser_inspection_failed"
        elif any(c.can_parse for c in candidates):
            rejected_reason = "no_plugin_above_confidence_threshold"
        return (
            ResolverDiagnostics(
                source_path=normalized_path,
                source_format=source_format,
                candidates_considered=tuple(candidates),
                selected=None,
                rejected_reason=rejected_reason,
                source_inspection=source_inspection,
                **diagnostic_metadata,
            ),
            None,
        )

    def evidence_rank(match: ProbeResult) -> tuple[int, int, int]:
        return (
            1 if match.semantic_row_count is not None and match.semantic_row_count > 0 else 0,
            match.confidence,
            priorities[match.plugin_id],
        )

    selected = max(parseable, key=evidence_rank)
    selected_rank = evidence_rank(selected)
    tied_plugin_ids = tuple(
        sorted(
            candidate.plugin_id
            for candidate in parseable
            if evidence_rank(candidate) == selected_rank
        )
    )
    if len(tied_plugin_ids) > 1:
        diagnostics = ResolverDiagnostics(
            source_path=normalized_path,
            source_format=source_format,
            candidates_considered=tuple(candidates),
            selected=None,
            rejected_reason="ambiguous_parser_match",
            source_inspection=source_inspection,
            ambiguous_plugin_ids=tied_plugin_ids,
            **diagnostic_metadata,
        )
        raise ParserAmbiguityError(diagnostics, tied_plugin_ids)

    return (
        ResolverDiagnostics(
            source_path=normalized_path,
            source_format=source_format,
            candidates_considered=tuple(candidates),
            selected=selected,
            source_inspection=source_inspection,
            **diagnostic_metadata,
        ),
        registrations_by_id[selected.plugin_id],
    )


def resolve_parser_with_diagnostics(
    file_path: str | Path,
    *,
    source_inspection: SourceInspectionContext | None = None,
) -> ResolverDiagnostics:
    """Resolve a plugin by semantic evidence, confidence, and priority."""

    diagnostics, _registration = _resolve_parser_with_registration(
        file_path,
        source_inspection=source_inspection,
    )
    return diagnostics


def detect_format(file_path: str | Path) -> str:
    """Backward-compatible format identifier detection."""

    diagnostics = resolve_parser_with_diagnostics(file_path)
    return diagnostics.selected.plugin_id if diagnostics.selected else "unknown"


def _resolve_parser_for_construction(
    normalized_path: str,
    *,
    source_inspection: SourceInspectionContext | None,
    expected_plugin_id: str | None,
    expected_registry_generation_id: int | None,
) -> tuple[ResolverDiagnostics, ParserRegistration | None]:
    """Resolve once and translate only reviewed late ambiguity to approval drift."""

    try:
        return _resolve_parser_with_registration(
            normalized_path,
            source_inspection=source_inspection,
        )
    except ParserAmbiguityError as exc:
        if (
            expected_plugin_id is None
            and expected_registry_generation_id is None
        ):
            raise
        raise ParserApprovalMismatchError(
            exc.diagnostics,
            expected_plugin_id=expected_plugin_id,
            expected_registry_generation_id=expected_registry_generation_id,
        ) from exc


def get_parser(
    file_path: str | Path,
    database: str,
    connection=None,
    metadata_parsing_mode=None,
    source_inspection: SourceInspectionContext | None = None,
    expected_plugin_id: str | None = None,
    expected_registry_generation_id: int | None = None,
):
    """Resolve once, validate optional reviewed approval, and construct a parser."""

    normalized_path = _as_file_path(file_path)
    approval_expected = (
        expected_plugin_id is not None
        or expected_registry_generation_id is not None
    )
    diagnostics, registration = _resolve_parser_for_construction(
        normalized_path,
        source_inspection=source_inspection,
        expected_plugin_id=expected_plugin_id,
        expected_registry_generation_id=expected_registry_generation_id,
    )
    resolved_plugin_id = (
        diagnostics.selected.plugin_id
        if diagnostics.selected is not None
        else None
    )
    if approval_expected and (
        resolved_plugin_id != expected_plugin_id
        or diagnostics.registry_generation_id
        != expected_registry_generation_id
        or registration is None
        or registration.plugin_id != expected_plugin_id
    ):
        raise ParserApprovalMismatchError(
            diagnostics,
            expected_plugin_id=expected_plugin_id,
            expected_registry_generation_id=expected_registry_generation_id,
        )
    if diagnostics.selected is None or registration is None:
        if diagnostics.rejected_reason == "parser_inspection_failed":
            raise ParserInspectionError(diagnostics)
        raise UnsupportedReportFormatError(diagnostics)

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
    parser.parser_resolution_evidence = ParserResolutionEvidence(
        plugin_id=registration.plugin_id,
        registry_generation_id=diagnostics.registry_generation_id,
        registration=registration,
        diagnostics=diagnostics,
    )

    if metadata_parsing_mode is not None and hasattr(parser, "metadata_parsing_mode"):
        parser.metadata_parsing_mode = metadata_parsing_mode

    return parser

def invoke_parser_factory(
    parser_factory,
    file_path: str | Path,
    *args,
    source_inspection: SourceInspectionContext | None = None,
    expected_plugin_id: str | None = None,
    expected_registry_generation_id: int | None = None,
    **kwargs,
):
    """Invoke old or context-aware parser factories without masking callback errors."""

    factory_kwargs = dict(kwargs)
    if source_inspection is not None and _callable_accepts_keyword(
        parser_factory,
        "source_inspection",
    ):
        factory_kwargs["source_inspection"] = source_inspection
    if expected_plugin_id is not None and _callable_accepts_keyword(
        parser_factory,
        "expected_plugin_id",
    ):
        factory_kwargs["expected_plugin_id"] = expected_plugin_id
    if expected_registry_generation_id is not None and _callable_accepts_keyword(
        parser_factory,
        "expected_registry_generation_id",
    ):
        factory_kwargs["expected_registry_generation_id"] = (
            expected_registry_generation_id
        )
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


def _validate_parser_class(
    plugin_id: str,
    parser_cls: ParserType,
    detector: DetectorType | None,
) -> None:
    if not isinstance(plugin_id, str) or _PLUGIN_ID_PATTERN.fullmatch(plugin_id) is None:
        raise ParserRegistrationError(
            "plugin_id must match ^[a-z][a-z0-9_.-]{0,127}$"
        )
    if not inspect.isclass(parser_cls) or not issubclass(parser_cls, BaseReportParserPlugin):
        raise ParserRegistrationError(
            "parser_cls must be a BaseReportParserPlugin subclass"
        )
    if inspect.isabstract(parser_cls):
        raise ParserRegistrationError("parser_cls must be concrete")
    if detector is not None and not callable(detector):
        raise ParserRegistrationError("detector must be callable")


def _validate_parser_manifest(plugin_id: str, manifest: PluginManifest) -> None:
    if not isinstance(manifest, PluginManifest):
        raise ParserRegistrationError("manifest must be a PluginManifest")
    if manifest.plugin_id != plugin_id:
        raise ParserRegistrationError(
            f"manifest plugin_id {manifest.plugin_id!r} does not match {plugin_id!r}"
        )
    if not isinstance(manifest.display_name, str) or not manifest.display_name.strip():
        raise ParserRegistrationError("manifest display_name must be non-empty")
    if not isinstance(manifest.version, str) or not manifest.version.strip():
        raise ParserRegistrationError("manifest version must be non-empty")
    if (
        not isinstance(manifest.supported_formats, tuple)
        or not manifest.supported_formats
        or any(
            not isinstance(source_format, str)
            or not source_format
            or source_format != source_format.strip().lower()
            for source_format in manifest.supported_formats
        )
    ):
        raise ParserRegistrationError(
            "manifest supported_formats must be a non-empty tuple of normalized strings"
        )
    if (
        isinstance(manifest.priority, bool)
        or not isinstance(manifest.priority, int)
        or not 0 <= manifest.priority <= 1000
    ):
        raise ParserRegistrationError("manifest priority must be an integer from 0 to 1000")


def _validate_parser_runtime_signatures(
    parser_cls: ParserType,
    detector: DetectorType | None,
) -> None:
    try:
        constructor_signature = inspect.signature(parser_cls)
        constructor_signature.bind("report.pdf", ":memory:", connection=None)
    except (TypeError, ValueError) as exc:
        raise ParserRegistrationError(
            "parser constructor must accept (file_path, database, connection=None)"
        ) from exc

    probe_context = ProbeContext(source_path="report.pdf", source_format="pdf")
    probe_callback = detector or parser_cls.probe
    try:
        probe_signature = inspect.signature(probe_callback)
        if detector is not None and _callable_accepts_keyword(detector, "probe_context"):
            probe_signature.bind("report.pdf", probe_context=probe_context)
        elif detector is not None:
            probe_signature.bind("report.pdf")
        else:
            probe_signature.bind("report.pdf", probe_context)
    except (TypeError, ValueError) as exc:
        expected = (
            "detector must accept (file_path) or (file_path, *, probe_context=...)"
            if detector is not None
            else "parser probe must accept (input_ref, context)"
        )
        raise ParserRegistrationError(expected) from exc


def _validate_parser_registration(
    plugin_id: str,
    parser_cls: ParserType,
    manifest: PluginManifest,
    detector: DetectorType | None,
) -> None:
    """Reject malformed registry entries before they can affect resolution."""

    _validate_parser_class(plugin_id, parser_cls, detector)
    _validate_parser_manifest(plugin_id, manifest)
    _validate_parser_runtime_signatures(parser_cls, detector)


def _commit_parser_registration(
    *,
    plugin_id: str,
    parser_cls: ParserType,
    manifest: PluginManifest,
    detector: DetectorType | None,
    replace: bool,
    builtin: bool,
) -> None:
    _validate_parser_registration(plugin_id, parser_cls, manifest, detector)
    if plugin_id == "cmm" and not builtin:
        raise ReservedParserPluginError("plugin id 'cmm' is reserved for the built-in parser")

    with _EXTERNAL_PLUGIN_REFRESH_LOCK:
        with _PARSER_REGISTRY_LOCK:
            snapshot = _synchronize_compatibility_maps_locked()
            existing = next(
                (
                    registration
                    for registration in snapshot.registrations
                    if registration.plugin_id == plugin_id
                ),
                None,
            )
            if existing is not None:
                if plugin_id == "cmm":
                    raise ReservedParserPluginError(
                        "the built-in 'cmm' parser cannot be replaced"
                    )
                if not replace:
                    raise DuplicateParserRegistrationError(
                        f"parser plugin {plugin_id!r} is already registered; pass replace=True "
                        "for an explicit non-built-in replacement"
                    )
            registration = ParserRegistration(
                plugin_id=plugin_id,
                parser_cls=parser_cls,
                manifest=manifest,
                detector=detector,
                origin="builtin" if builtin else "manual",
                origin_ref="metroliza" if builtin else "runtime",
            )
            registrations = list(snapshot.registrations)
            if existing is not None:
                registrations[registrations.index(existing)] = registration
            else:
                registrations.append(registration)
            if builtin:
                _MANUAL_REGISTRATIONS.pop(plugin_id, None)
            else:
                _MANUAL_REGISTRATIONS[plugin_id] = registration
                _DIRECT_EXTERNAL_REGISTRATIONS.pop(plugin_id, None)
            _publish_registry_locked(tuple(registrations), load_errors=snapshot.load_errors)


def register_parser(
    parser_or_format: ParserType | str,
    parser_cls: ParserType | None = None,
    *,
    detector: DetectorType | None = None,
    manifest: PluginManifest | None = None,
    replace: bool = False,
):
    """Register parser plugin class.

    Supported call styles:
    - ``register_parser(ParserClass)``
    - ``register_parser("plugin_id", ParserClass, detector=..., manifest=...)``

    Duplicate ids are rejected.  Callers may pass ``replace=True`` only for an
    intentional replacement of a non-built-in parser.
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

    _commit_parser_registration(
        plugin_id=plugin_id,
        parser_cls=parser_cls,
        manifest=plugin_manifest,
        detector=detector,
        replace=replace,
        builtin=False,
    )


_commit_parser_registration(
    plugin_id="cmm",
    parser_cls=CMMReportParser,
    detector=_default_cmm_detector,
    manifest=CMMReportParser.manifest,
    replace=False,
    builtin=True,
)
