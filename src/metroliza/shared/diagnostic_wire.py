"""Strict byte boundary for closed diagnostic events."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable

from metroliza.shared.diagnostic_events import (
    BuildPackager,
    DiagnosticEvent,
    DiagnosticEventValidationError,
    DiagnosticOperation,
    ExceptionDiagnosticEvent,
    ExceptionKind,
    InvalidDiagnosticEvent,
    LegacyLogSuppressedEvent,
    RuntimeMode,
    RuntimeProvenanceEvent,
    SourceClass,
    StartupCallsite,
    StartupDiagnosticEvent,
    StartupMode,
    StartupOutcome,
    ValidationStatus,
    WorkflowDiagnosticEvent,
    WorkflowError,
    WorkflowOperation,
    WorkflowOutcome,
    WorkflowStage,
    serialize_diagnostic_event,
)


MAX_EVENT_BYTES = 4096
_WIRE_ERROR = "invalid diagnostic wire event"
_UUID_HEX = re.compile(r"[0-9a-f]{32}\Z")
_RELEASE = re.compile(r"(?P<year>[0-9]{4})\.(?P<month>[0-9]{2})(?:rc(?P<rc>[1-9][0-9]{0,2}))?\Z")


class WireValidationError(ValueError):
    """Raised without reflecting peer-controlled bytes."""


def encode_event(event: object) -> bytes:
    """Encode through the canonical safe-event serializer."""
    try:
        payload = serialize_diagnostic_event(event).encode("ascii")
    except (DiagnosticEventValidationError, UnicodeEncodeError):
        raise WireValidationError(_WIRE_ERROR) from None
    if not payload or len(payload) > MAX_EVENT_BYTES:
        raise WireValidationError(_WIRE_ERROR)
    return payload


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WireValidationError(_WIRE_ERROR)
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise WireValidationError(_WIRE_ERROR)


def _exact_keys(payload: object, keys: tuple[str, ...]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != set(keys):
        raise WireValidationError(_WIRE_ERROR)
    return payload


def _enum(enum_type: Callable[[object], object], value: object) -> object:
    if type(value) is not str:
        raise WireValidationError(_WIRE_ERROR)
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        raise WireValidationError(_WIRE_ERROR) from None


def _uuid(value: object) -> uuid.UUID:
    if type(value) is not str or _UUID_HEX.fullmatch(value) is None:
        raise WireValidationError(_WIRE_ERROR)
    return uuid.UUID(hex=value)


_EXCEPTION_KEYS = (
    "event_code",
    "operation",
    "exception_kind",
    "correlation_id",
    "has_traceback",
    "traceback_frames",
    "cause_count",
    "context_count",
    "group_count",
    "group_member_count",
    "structure_truncated",
)
_NESTED_EXCEPTION_KEYS = (
    "exception_kind",
    "has_traceback",
    "traceback_frames",
    "cause_count",
    "context_count",
    "group_count",
    "group_member_count",
    "structure_truncated",
)


def _exception(payload: object, *, nested: bool = False) -> ExceptionDiagnosticEvent:
    values = _exact_keys(payload, _NESTED_EXCEPTION_KEYS if nested else _EXCEPTION_KEYS)
    event = ExceptionDiagnosticEvent(
        operation=(
            DiagnosticOperation.UNHANDLED_EXCEPTION
            if nested
            else _enum(DiagnosticOperation, values["operation"])
        ),
        exception_kind=_enum(ExceptionKind, values["exception_kind"]),
        has_traceback=values["has_traceback"],
        traceback_frames=values["traceback_frames"],
        cause_count=values["cause_count"],
        context_count=values["context_count"],
        group_count=values["group_count"],
        group_member_count=values["group_member_count"],
        structure_truncated=values["structure_truncated"],
    )
    if not nested:
        object.__setattr__(event, "correlation_id", _uuid(values["correlation_id"]))
    return event


def _source(payload: object, *, invalid: bool) -> DiagnosticEvent:
    values = _exact_keys(payload, ("event_code", "source_class"))
    source_class = _enum(SourceClass, values["source_class"])
    return (
        InvalidDiagnosticEvent(source_class) if invalid else LegacyLogSuppressedEvent(source_class)
    )


def _runtime(payload: object) -> RuntimeProvenanceEvent:
    values = _exact_keys(
        payload,
        (
            "event_code",
            "invocation_id",
            "startup_id",
            "sequence",
            "release_version",
            "git_sha",
            "runtime",
            "packager",
            "dirty",
        ),
    )
    release = values["release_version"]
    if type(release) is not str or (match := _RELEASE.fullmatch(release)) is None:
        raise WireValidationError(_WIRE_ERROR)
    return RuntimeProvenanceEvent(
        invocation_id=_uuid(values["invocation_id"]),
        startup_id=_uuid(values["startup_id"]),
        sequence=values["sequence"],
        runtime=_enum(RuntimeMode, values["runtime"]),
        packager=_enum(BuildPackager, values["packager"]),
        git_sha=values["git_sha"],
        dirty=values["dirty"],
        release_year=int(match.group("year")),
        release_month=int(match.group("month")),
        release_candidate=int(candidate) if (candidate := match.group("rc")) else None,
    )


def _startup(payload: object) -> StartupDiagnosticEvent:
    values = _exact_keys(
        payload,
        (
            "event_code",
            "invocation_id",
            "startup_id",
            "sequence",
            "mode",
            "callsite",
            "outcome",
            "exit_code",
            "exception",
        ),
    )
    exception = values["exception"]
    return StartupDiagnosticEvent(
        invocation_id=_uuid(values["invocation_id"]),
        startup_id=_uuid(values["startup_id"]),
        sequence=values["sequence"],
        mode=_enum(StartupMode, values["mode"]),
        callsite=_enum(StartupCallsite, values["callsite"]),
        outcome=_enum(StartupOutcome, values["outcome"]),
        exit_code=values["exit_code"],
        exception=None if exception is None else _exception(exception, nested=True),
    )


def _workflow(payload: object) -> WorkflowDiagnosticEvent:
    values = _exact_keys(
        payload,
        (
            "event_code",
            "invocation_id",
            "operation_id",
            "sequence",
            "operation",
            "stage",
            "outcome",
            "error",
            "validation_status",
            "selected_report_count",
            "published_artifact_count",
            "duration_ms",
        ),
    )
    return WorkflowDiagnosticEvent(
        invocation_id=_uuid(values["invocation_id"]),
        operation_id=_uuid(values["operation_id"]),
        sequence=values["sequence"],
        operation=_enum(WorkflowOperation, values["operation"]),
        stage=_enum(WorkflowStage, values["stage"]),
        outcome=_enum(WorkflowOutcome, values["outcome"]),
        error=_enum(WorkflowError, values["error"]),
        validation_status=_enum(ValidationStatus, values["validation_status"]),
        selected_report_count=values["selected_report_count"],
        published_artifact_count=values["published_artifact_count"],
        duration_ms=values["duration_ms"],
    )


def _reconstruct(payload: object) -> DiagnosticEvent:
    if type(payload) is not dict or type(payload.get("event_code")) is not str:
        raise WireValidationError(_WIRE_ERROR)
    code = payload["event_code"]
    if code == "legacy_log_suppressed":
        return _source(payload, invalid=False)
    if code == "invalid_diagnostic_event":
        return _source(payload, invalid=True)
    if code == "exception_diagnostic":
        return _exception(payload)
    if code == "runtime_provenance":
        return _runtime(payload)
    if code == "startup_diagnostic":
        return _startup(payload)
    if code == "workflow_diagnostic":
        return _workflow(payload)
    raise WireValidationError(_WIRE_ERROR)


def decode_event(data: bytes) -> DiagnosticEvent:
    """Reconstruct one exact canonical event from bounded untrusted bytes."""
    if type(data) is not bytes or not data or len(data) > MAX_EVENT_BYTES:
        raise WireValidationError(_WIRE_ERROR)
    try:
        text = data.decode("ascii")
        payload = json.loads(
            text,
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
        event = _reconstruct(payload)
        if encode_event(event) != data:
            raise WireValidationError(_WIRE_ERROR)
        return event
    except WireValidationError:
        raise
    except (
        DiagnosticEventValidationError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
        KeyError,
        AttributeError,
        OverflowError,
    ):
        raise WireValidationError(_WIRE_ERROR) from None
