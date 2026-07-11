"""Validated configuration objects for realtime industrial polling."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from metroliza.industrial.industrial_data_repository import looks_sensitive_key, redact_sensitive_text
from metroliza.industrial.industrial_workflow_state import require_identifier
from metroliza.industrial.realtime.detector_registry import (
    UnsupportedRealtimeDetectorError,
    normalize_detector_keys,
)
from metroliza.industrial.realtime.numeric_validation import exact_integral, finite_number
from metroliza.industrial.realtime.timestamps import (
    IndustrialTimestampError,
    validate_source_timezone,
)


class RealtimeStreamConfigError(ValueError):
    """Raised when a realtime industrial stream config is invalid or unsafe."""


DEFAULT_SEGMENT_FIELDS = ("reference", "part_number", "revision", "station", "line")
DEFAULT_CONTEXT_FIELDS = (
    "reference",
    "part_number",
    "revision",
    "station",
    "line",
    "work_order",
    "batch_lot",
)
_SQL_DIAGNOSTIC_KEYS = frozenset(
    {"sql", "sqltext", "sql_text", "statement", "query", "rawsql", "raw_sql"}
)
_DIAGNOSTIC_SENSITIVE_COMPACT_KEYS = frozenset(
    {
        "connectionstring",
        "datasource",
        "dsn",
        "host",
        "hostname",
        "login",
        "querysummary",
        "server",
        "sqlalchemyurl",
        "uid",
        "uri",
        "url",
        "user",
        "userid",
        "username",
    }
)
_URI_WITH_CREDENTIALS = re.compile(
    r"([a-zA-Z][a-zA-Z0-9+.\-]*://)([^:/@\s]+):([^@/\s]+)@([^/\s?#]+)"
)


@dataclass(frozen=True)
class RealtimePollConfig:
    """Configuration for one bounded realtime polling stream."""

    source_profile_id: int
    stream_key: str
    cursor_column: str
    event_time_column: str
    record_key_column: str
    signal_keys: tuple[str, ...]
    signal_columns: Mapping[str, str] = field(default_factory=dict)
    enabled: bool = True
    polling_interval_seconds: float = 60.0
    chunk_size: int = 500
    max_catchup_rows_per_cycle: int = 5_000
    allowed_lateness_seconds: float = 0.0
    source_timezone: str = "UTC"
    timeout_seconds: float = 30.0
    segment_fields: tuple[str, ...] = DEFAULT_SEGMENT_FIELDS
    context_fields: tuple[str, ...] = DEFAULT_CONTEXT_FIELDS
    detectors: tuple[str, ...] = ("spec_limits",)
    fetch_all_confirmed: bool = False

    def validated(self) -> "RealtimePollConfig":
        """Return a normalized, bounded realtime config or raise a safety error."""

        source_profile_id = _positive_int("source profile id", self.source_profile_id)
        if type(self.enabled) is not bool:
            raise RealtimeStreamConfigError("Realtime enabled setting must be true or false.")
        if self.fetch_all_confirmed:
            raise RealtimeStreamConfigError(
                "Realtime polling never accepts fetch-all confirmation; configure a cursor and limit."
            )
        stream_key = _require_simple_identifier("stream key", self.stream_key)
        cursor_column = _require_simple_identifier("cursor column", self.cursor_column)
        event_time_column = _require_simple_identifier("event time column", self.event_time_column)
        record_key_column = _require_simple_identifier("record key column", self.record_key_column)
        signal_keys = _normalize_identifier_tuple("signal key", self.signal_keys)
        if not signal_keys:
            raise RealtimeStreamConfigError("Configure at least one realtime signal key.")

        signal_columns = {
            signal_key: _require_simple_identifier(
                f"metric column for signal '{signal_key}'",
                self.signal_columns.get(signal_key, signal_key),
            )
            for signal_key in signal_keys
        }
        segment_fields = _normalize_identifier_tuple("segment field", self.segment_fields)
        context_fields = _normalize_identifier_tuple("context field", self.context_fields)
        try:
            detectors = normalize_detector_keys(self.detectors)
        except UnsupportedRealtimeDetectorError as exc:
            raise RealtimeStreamConfigError(str(exc)) from exc
        if not detectors:
            raise RealtimeStreamConfigError("Configure at least one detector for realtime polling.")
        try:
            source_timezone = validate_source_timezone(self.source_timezone)
        except IndustrialTimestampError as exc:
            raise RealtimeStreamConfigError(str(exc)) from exc

        polling_interval = _positive_float(
            "polling interval seconds",
            self.polling_interval_seconds,
        )
        chunk_size = _positive_int("chunk size", self.chunk_size)
        max_catchup = _positive_int("max catchup rows per cycle", self.max_catchup_rows_per_cycle)
        if max_catchup < chunk_size:
            raise RealtimeStreamConfigError(
                "Max catchup rows per cycle must be greater than or equal to chunk size."
            )
        allowed_lateness = _nonnegative_float(
            "allowed lateness seconds",
            self.allowed_lateness_seconds,
        )
        timeout = _positive_float("timeout seconds", self.timeout_seconds)
        if timeout > polling_interval:
            raise RealtimeStreamConfigError(
                "Realtime query timeout seconds must be less than or equal to polling interval seconds."
            )

        return replace(
            self,
            source_profile_id=source_profile_id,
            stream_key=stream_key,
            cursor_column=cursor_column,
            event_time_column=event_time_column,
            record_key_column=record_key_column,
            signal_keys=signal_keys,
            signal_columns=signal_columns,
            enabled=bool(self.enabled),
            polling_interval_seconds=polling_interval,
            chunk_size=chunk_size,
            max_catchup_rows_per_cycle=max_catchup,
            allowed_lateness_seconds=allowed_lateness,
            source_timezone=source_timezone,
            timeout_seconds=timeout,
            segment_fields=segment_fields,
            context_fields=context_fields,
            detectors=detectors,
            fetch_all_confirmed=False,
        )

    @property
    def cycle_limit(self) -> int:
        """Return the enforced per-query row bound for one polling cycle."""

        return min(int(self.chunk_size), int(self.max_catchup_rows_per_cycle))


def reject_sensitive_config_payload(payload: Mapping[str, Any]) -> None:
    """Reject credential-like keys in a user-provided realtime config payload."""

    sensitive_paths = sorted(_sensitive_paths(payload))
    if sensitive_paths:
        joined = ", ".join(sensitive_paths)
        raise RealtimeStreamConfigError(
            f"Realtime streaming config contains credential-like key(s): {joined}. "
            "Move credentials to the local credential store or environment variables."
        )


def hash_sql_text(sql_text: str) -> str:
    """Return a stable digest for SQL diagnostics without retaining SQL text."""

    normalized = " ".join(str(sql_text or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def safe_query_diagnostics(
    *,
    sql_text: str,
    query_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build SQL diagnostics with only a digest and redacted summary metadata."""

    diagnostics: dict[str, Any] = {"sql_hash": hash_sql_text(sql_text)}
    if query_summary:
        diagnostics["query_summary"] = redact_stream_diagnostics(query_summary)
    return diagnostics


def redact_stream_diagnostics(value: Any) -> Any:
    """Redact credential-like fields and raw SQL from nested diagnostics."""

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            key_text = str(key)
            normalized_key = _compact_key(key_text)
            if (
                looks_sensitive_key(key_text)
                or normalized_key in _SQL_DIAGNOSTIC_KEYS
                or normalized_key in _DIAGNOSTIC_SENSITIVE_COMPACT_KEYS
            ):
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = redact_stream_diagnostics(nested)
        return redacted
    if isinstance(value, tuple):
        return tuple(redact_stream_diagnostics(item) for item in value)
    if isinstance(value, list):
        return [redact_stream_diagnostics(item) for item in value]
    if isinstance(value, str):
        return _redact_stream_text(value)
    return value


def _require_simple_identifier(field_name: str, value: Any) -> str:
    text = str(value or "").strip()
    try:
        require_identifier(field_name, text)
    except ValueError as exc:
        raise RealtimeStreamConfigError(str(exc)) from exc
    return text


def _normalize_identifier_tuple(field_name: str, values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        text = _require_simple_identifier(field_name, value)
        if text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)


def _positive_int(field_name: str, value: Any) -> int:
    try:
        return exact_integral(value, field_name=field_name, minimum=1)
    except ValueError as exc:
        raise RealtimeStreamConfigError(f"Realtime {field_name} must be a positive integer.") from exc


def _positive_float(field_name: str, value: Any) -> float:
    try:
        return finite_number(
            value,
            field_name=field_name,
            minimum=0.0,
            minimum_inclusive=False,
        )
    except ValueError as exc:
        raise RealtimeStreamConfigError(f"Realtime {field_name} must be a positive number.") from exc


def _nonnegative_float(field_name: str, value: Any) -> float:
    try:
        return finite_number(value, field_name=field_name, minimum=0.0)
    except ValueError as exc:
        raise RealtimeStreamConfigError(
            f"Realtime {field_name} must be a finite non-negative number."
        ) from exc


def _sensitive_paths(value: Any, *, prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if looks_sensitive_key(key_text):
                found.add(path)
            found.update(_sensitive_paths(nested, prefix=path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.update(_sensitive_paths(nested, prefix=f"{prefix}[{index}]"))
    return found


def _redact_stream_text(value: str) -> str:
    text = _URI_WITH_CREDENTIALS.sub(r"\1<redacted>:<redacted>@<redacted>", str(value or ""))
    return redact_sensitive_text(text, max_len=None)


def _compact_key(key: str) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())
