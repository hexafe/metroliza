"""Validated configuration for realtime industrial polling streams."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any

import yaml

from metroliza.industrial.industrial_data_repository import (
    IndustrialSourceProfile,
    looks_sensitive_key,
    redact_sensitive_text,
)
from metroliza.industrial.industrial_source_config import IndustrialSourceConfigError
from metroliza.industrial.industrial_workflow_state import require_identifier
from metroliza.industrial.realtime.stream_contracts import SignalDefinition


REALTIME_STREAM_CONFIG_ROOT_KEY = "realtime_streams"
_DEFAULT_BATCH_LIMIT = 500
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_LAG_SECONDS = 300.0
_DEFAULT_HISTORY_LIMIT = 1_000
_SQL_DIAGNOSTIC_KEYS = frozenset({"sql", "sql_text", "statement", "query", "raw_sql"})


class RealtimeStreamConfigError(IndustrialSourceConfigError):
    """Raised when a realtime industrial stream config is invalid or unsafe."""


@dataclass(frozen=True)
class StreamPollPolicy:
    """Bounded polling policy for one realtime source stream."""

    batch_limit: int = _DEFAULT_BATCH_LIMIT
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_lag_seconds: float = _DEFAULT_MAX_LAG_SECONDS
    history_limit: int = _DEFAULT_HISTORY_LIMIT
    allow_initial_poll_without_cursor: bool = True

    def validated(self) -> "StreamPollPolicy":
        batch_limit = int(self.batch_limit)
        timeout_seconds = float(self.timeout_seconds)
        max_lag_seconds = float(self.max_lag_seconds)
        history_limit = int(self.history_limit)
        if batch_limit < 1:
            raise RealtimeStreamConfigError("Realtime batch limit must be at least 1.")
        if timeout_seconds <= 0:
            raise RealtimeStreamConfigError("Realtime query timeout must be greater than 0 seconds.")
        if max_lag_seconds < 0:
            raise RealtimeStreamConfigError("Realtime max lag must not be negative.")
        if history_limit < 0:
            raise RealtimeStreamConfigError("Realtime detector history limit must not be negative.")
        if type(self.allow_initial_poll_without_cursor) is not bool:
            raise RealtimeStreamConfigError(
                "Realtime initial cursor policy must be true or false."
            )
        return StreamPollPolicy(
            batch_limit=batch_limit,
            timeout_seconds=timeout_seconds,
            max_lag_seconds=max_lag_seconds,
            history_limit=history_limit,
            allow_initial_poll_without_cursor=self.allow_initial_poll_without_cursor,
        )


@dataclass(frozen=True)
class RealtimeStreamConfig:
    """One non-secret realtime mapping from a source profile row to a signal."""

    source_profile_id: int
    stream_key: str
    signal_key: str
    metric_column: str
    event_time_column: str
    record_key_column: str
    enabled: bool = True
    metric_name: str | None = None
    unit: str | None = None
    nominal: float | None = None
    lsl: float | None = None
    usl: float | None = None
    lower_warning: float | None = None
    upper_warning: float | None = None
    segment_fields: tuple[str, ...] = ()
    context_columns: tuple[str, ...] = ()
    detectors: tuple[str, ...] = ("spec_limits", "rolling_zscore")
    policy: StreamPollPolicy = field(default_factory=StreamPollPolicy)

    def validated(self, *, profile: IndustrialSourceProfile | None = None) -> "RealtimeStreamConfig":
        if type(self.enabled) is not bool:
            raise RealtimeStreamConfigError("Realtime stream enabled setting must be true or false.")
        source_profile_id = int(self.source_profile_id)
        if source_profile_id < 1:
            raise RealtimeStreamConfigError("Realtime stream source_profile_id must be positive.")
        if profile is not None and profile.id and source_profile_id != int(profile.id):
            raise RealtimeStreamConfigError(
                "Realtime stream source_profile_id does not match the selected source profile."
            )

        stream_key = _required_identifier("stream key", self.stream_key)
        signal_key = _required_identifier("signal key", self.signal_key)
        metric_column = _required_identifier("metric column", self.metric_column)
        event_time_column = _required_identifier("event time column", self.event_time_column)
        record_key_column = _required_identifier("record key column", self.record_key_column)
        metric_name = str(self.metric_name or metric_column).strip()
        if not metric_name:
            raise RealtimeStreamConfigError("Realtime stream metric name must not be empty.")

        segment_fields = _normalize_identifiers("segment field", self.segment_fields)
        context_columns = _normalize_identifiers("context column", self.context_columns)
        detectors = _normalize_identifiers("detector key", self.detectors)
        policy = self.policy.validated()

        _validate_profile_allowlist(
            profile,
            columns=(metric_column, event_time_column, record_key_column, *segment_fields, *context_columns),
        )
        return RealtimeStreamConfig(
            source_profile_id=source_profile_id,
            stream_key=stream_key,
            signal_key=signal_key,
            metric_column=metric_column,
            event_time_column=event_time_column,
            record_key_column=record_key_column,
            enabled=self.enabled,
            metric_name=metric_name,
            unit=str(self.unit or "").strip() or None,
            nominal=_optional_float(self.nominal, "nominal"),
            lsl=_optional_float(self.lsl, "lsl"),
            usl=_optional_float(self.usl, "usl"),
            lower_warning=_optional_float(self.lower_warning, "lower warning"),
            upper_warning=_optional_float(self.upper_warning, "upper warning"),
            segment_fields=segment_fields,
            context_columns=context_columns,
            detectors=detectors,
            policy=policy,
        )


RealtimePollConfig = RealtimeStreamConfig


def load_realtime_stream_configs(config_path: str | Path) -> list[RealtimeStreamConfig]:
    """Load non-secret realtime stream definitions from a YAML config file."""

    path = Path(config_path).expanduser()
    if not path.exists():
        return []
    payload = _read_config_payload(path)
    streams = _streams_payload(payload, path)
    configs: list[RealtimeStreamConfig] = []
    for fallback_key, entry in streams:
        if not isinstance(entry, Mapping):
            raise RealtimeStreamConfigError(
                f"Realtime stream '{fallback_key}' in '{path}' must be a mapping."
            )
        _raise_if_sensitive(entry, stream_key=fallback_key, path=path)
        configs.append(_stream_from_entry(fallback_key, entry, path=path))
    return configs


def validate_stream_config(
    config: RealtimeStreamConfig,
    profile: IndustrialSourceProfile | None = None,
) -> RealtimeStreamConfig:
    """Validate one realtime stream config against an optional source profile."""

    return config.validated(profile=profile)


def signal_definition_from_stream(config: RealtimeStreamConfig) -> SignalDefinition:
    """Build the signal definition represented by a validated realtime stream config."""

    validated = config.validated()
    return SignalDefinition(
        source_profile_id=validated.source_profile_id,
        signal_key=validated.signal_key,
        metric_name=validated.metric_name or validated.metric_column,
        unit=validated.unit,
        nominal=validated.nominal,
        lsl=validated.lsl,
        usl=validated.usl,
        lower_warning=validated.lower_warning,
        upper_warning=validated.upper_warning,
        segment_fields=validated.segment_fields,
        enabled=validated.enabled,
    )


def realtime_source_columns(config: RealtimeStreamConfig) -> tuple[str, ...]:
    """Return the source columns a realtime poller must read for this stream."""

    validated = config.validated()
    columns = (
        validated.record_key_column,
        validated.event_time_column,
        validated.metric_column,
        *validated.segment_fields,
        *validated.context_columns,
    )
    seen: set[str] = set()
    ordered: list[str] = []
    for column in columns:
        if column in seen:
            continue
        seen.add(column)
        ordered.append(column)
    return tuple(ordered)


def hash_sql_text(sql_text: str) -> str:
    """Return a stable digest for SQL diagnostics without persisting the SQL text."""

    normalized = " ".join(str(sql_text or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def safe_query_diagnostics(
    *,
    sql_text: str,
    query_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build SQL diagnostics that keep only a hash and redacted non-SQL summary fields."""

    diagnostics: dict[str, Any] = {"sql_hash": hash_sql_text(sql_text)}
    if query_summary:
        diagnostics["query_summary"] = redact_stream_diagnostics(query_summary)
    return diagnostics


def redact_stream_diagnostics(value: Any) -> Any:
    """Redact credential-like and raw SQL values from nested stream diagnostics."""

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            key_text = str(key)
            normalized_key = _compact_key(key_text)
            if looks_sensitive_key(key_text) or normalized_key in _SQL_DIAGNOSTIC_KEYS:
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = redact_stream_diagnostics(nested)
        return redacted
    if isinstance(value, tuple):
        return tuple(redact_stream_diagnostics(item) for item in value)
    if isinstance(value, list):
        return [redact_stream_diagnostics(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def _stream_from_entry(
    fallback_key: str,
    entry: Mapping[str, Any],
    *,
    path: Path,
) -> RealtimeStreamConfig:
    policy_payload = entry.get("policy", {})
    if policy_payload is None:
        policy_payload = {}
    if not isinstance(policy_payload, Mapping):
        raise RealtimeStreamConfigError(
            f"Realtime stream '{fallback_key}' in '{path}' has invalid policy: expected a mapping."
        )
    stream_key = str(entry.get("stream_key") or fallback_key)
    try:
        source_profile_id = int(entry["source_profile_id"])
    except KeyError as exc:
        raise RealtimeStreamConfigError(
            f"Realtime stream '{fallback_key}' in '{path}' is missing source_profile_id."
        ) from exc
    except (TypeError, ValueError) as exc:
        raise RealtimeStreamConfigError(
            f"Realtime stream '{fallback_key}' in '{path}' has invalid source_profile_id."
        ) from exc

    return RealtimeStreamConfig(
        source_profile_id=source_profile_id,
        stream_key=stream_key,
        signal_key=str(entry.get("signal_key") or stream_key),
        metric_column=_required_entry(entry, "metric_column", stream_key=stream_key, path=path),
        event_time_column=_required_entry(entry, "event_time_column", stream_key=stream_key, path=path),
        record_key_column=_required_entry(entry, "record_key_column", stream_key=stream_key, path=path),
        enabled=_bool_entry(entry.get("enabled", True), "enabled", stream_key=stream_key, path=path),
        metric_name=str(entry.get("metric_name") or "").strip() or None,
        unit=str(entry.get("unit") or "").strip() or None,
        nominal=_optional_float(entry.get("nominal"), "nominal"),
        lsl=_optional_float(entry.get("lsl"), "lsl"),
        usl=_optional_float(entry.get("usl"), "usl"),
        lower_warning=_optional_float(entry.get("lower_warning"), "lower_warning"),
        upper_warning=_optional_float(entry.get("upper_warning"), "upper_warning"),
        segment_fields=_normalize_sequence(entry.get("segment_fields", ()), "segment_fields"),
        context_columns=_normalize_sequence(entry.get("context_columns", ()), "context_columns"),
        detectors=_normalize_sequence(entry.get("detectors", ("spec_limits",)), "detectors"),
        policy=StreamPollPolicy(
            batch_limit=policy_payload.get("batch_limit", _DEFAULT_BATCH_LIMIT),
            timeout_seconds=policy_payload.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS),
            max_lag_seconds=policy_payload.get("max_lag_seconds", _DEFAULT_MAX_LAG_SECONDS),
            history_limit=policy_payload.get("history_limit", _DEFAULT_HISTORY_LIMIT),
            allow_initial_poll_without_cursor=_bool_entry(
                policy_payload.get("allow_initial_poll_without_cursor", True),
                "allow_initial_poll_without_cursor",
                stream_key=stream_key,
                path=path,
            ),
        ),
    ).validated()


def _read_config_payload(path: Path) -> Mapping[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RealtimeStreamConfigError(f"Invalid YAML in realtime stream config: {path}") from exc
    except OSError as exc:
        raise RealtimeStreamConfigError(f"Could not read realtime stream config: {path}") from exc
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise RealtimeStreamConfigError(f"Realtime stream config '{path}' must be a mapping.")
    return payload


def _streams_payload(payload: Mapping[str, Any], path: Path) -> list[tuple[str, Mapping[str, Any]]]:
    streams = payload.get(REALTIME_STREAM_CONFIG_ROOT_KEY)
    if streams is None:
        return []
    if isinstance(streams, Mapping):
        return [(str(key), value) for key, value in streams.items()]
    if isinstance(streams, list):
        return [(f"stream_{index + 1}", value) for index, value in enumerate(streams)]
    raise RealtimeStreamConfigError(
        f"Realtime stream config '{path}' must define a top-level 'realtime_streams' mapping or list."
    )


def _raise_if_sensitive(entry: Mapping[str, Any], *, stream_key: str, path: Path) -> None:
    sensitive_paths = sorted(_find_sensitive_paths(entry))
    if sensitive_paths:
        joined = ", ".join(sensitive_paths)
        raise RealtimeStreamConfigError(
            f"Realtime stream '{stream_key}' in '{path}' contains credential-like key(s): "
            f"{joined}. Move credentials to the local credential store or environment variables."
        )


def _find_sensitive_paths(value: Any, *, prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if looks_sensitive_key(key_text):
                found.add(path)
            found.update(_find_sensitive_paths(nested, prefix=path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.update(_find_sensitive_paths(nested, prefix=f"{prefix}[{index}]"))
    return found


def _validate_profile_allowlist(
    profile: IndustrialSourceProfile | None,
    *,
    columns: Iterable[str],
) -> None:
    if profile is None or not profile.allowed_columns:
        return
    allowed = {str(column).strip() for column in profile.allowed_columns if str(column).strip()}
    missing = sorted({column for column in columns if column and column not in allowed})
    if missing:
        raise RealtimeStreamConfigError(
            "Realtime stream uses column(s) outside the source profile allowlist: "
            + ", ".join(missing)
        )


def _normalize_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise RealtimeStreamConfigError(f"Realtime {field_name} must be a list of names.")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _normalize_identifiers(field_name: str, values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = _required_identifier(field_name, value)
        if text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)


def _required_identifier(field_name: str, value: str) -> str:
    text = str(value or "").strip()
    try:
        require_identifier(field_name, text)
    except ValueError as exc:
        raise RealtimeStreamConfigError(str(exc)) from exc
    return text


def _required_entry(
    entry: Mapping[str, Any],
    key: str,
    *,
    stream_key: str,
    path: Path,
) -> str:
    value = str(entry.get(key) or "").strip()
    if not value:
        raise RealtimeStreamConfigError(
            f"Realtime stream '{stream_key}' in '{path}' is missing {key}."
        )
    return value


def _bool_entry(value: Any, key: str, *, stream_key: str, path: Path) -> bool:
    if type(value) is bool:
        return value
    raise RealtimeStreamConfigError(
        f"Realtime stream '{stream_key}' in '{path}' has invalid '{key}': expected true or false."
    )


def _optional_float(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RealtimeStreamConfigError(f"Realtime {field_name} must be numeric.") from exc


def _compact_key(key: str) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum() or character == "_")
