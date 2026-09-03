"""Closed, bounded diagnostic events for Metroliza-managed log sinks."""

from __future__ import annotations

import json
import types
import uuid
from dataclasses import dataclass
from enum import Enum


_MAX_EXCEPTION_NODES = 32
_MAX_EXCEPTION_DEPTH = 8
_MAX_TRACEBACK_FRAMES = 64
_MAX_IDENTIFIER_LENGTH = 200
_UNKNOWN_EXCEPTION = "unknown_exception"


class DiagnosticEventValidationError(ValueError):
    """Raised when a diagnostic event does not match its closed schema."""


class DiagnosticEventCode(str, Enum):
    """Source-controlled event codes accepted by managed logging."""

    LEGACY_LOG_SUPPRESSED = "legacy_log_suppressed"
    INVALID_DIAGNOSTIC_EVENT = "invalid_diagnostic_event"
    EXCEPTION_DIAGNOSTIC = "exception_diagnostic"


class DiagnosticOperation(str, Enum):
    """Source-controlled operations that may emit exception diagnostics."""

    UNHANDLED_EXCEPTION = "unhandled_exception"
    QT_DIALOG_IMPORT_FAILURE = "qt_dialog_import_failure"


class SourceClass(str, Enum):
    """Coarse, non-identifying source classes for suppressed legacy logs."""

    APPLICATION = "application"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LegacyLogSuppressedEvent:
    """Fixed event emitted instead of an arbitrary legacy log payload."""

    source_class: SourceClass


@dataclass(frozen=True, slots=True)
class InvalidDiagnosticEvent:
    """Fixed event emitted when a typed event fails validation."""

    source_class: SourceClass


@dataclass(frozen=True, slots=True, init=False)
class ExceptionDiagnosticEvent:
    """Bounded exception type and shape without exception-controlled text."""

    operation: DiagnosticOperation
    exception_type: str
    correlation_id: uuid.UUID
    has_traceback: bool
    traceback_frames: int
    cause_count: int
    context_count: int
    group_count: int
    group_member_count: int
    structure_truncated: bool

    def __init__(
        self,
        *,
        operation: DiagnosticOperation,
        exception_type: str,
        has_traceback: bool,
        traceback_frames: int,
        cause_count: int,
        context_count: int,
        group_count: int,
        group_member_count: int,
        structure_truncated: bool,
    ) -> None:
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "exception_type", exception_type)
        object.__setattr__(self, "correlation_id", uuid.uuid4())
        object.__setattr__(self, "has_traceback", has_traceback)
        object.__setattr__(self, "traceback_frames", traceback_frames)
        object.__setattr__(self, "cause_count", cause_count)
        object.__setattr__(self, "context_count", context_count)
        object.__setattr__(self, "group_count", group_count)
        object.__setattr__(self, "group_member_count", group_member_count)
        object.__setattr__(self, "structure_truncated", structure_truncated)


DiagnosticEvent = LegacyLogSuppressedEvent | InvalidDiagnosticEvent | ExceptionDiagnosticEvent


def _is_identifier(value: object) -> bool:
    if type(value) is not str or not 1 <= len(value) <= _MAX_IDENTIFIER_LENGTH:
        return False
    for part in value.split("."):
        if not part or not (part[0].isascii() and (part[0].isalpha() or part[0] == "_")):
            return False
        if any(not (character.isascii() and (character.isalnum() or character == "_")) for character in part[1:]):
            return False
    return True


def _exception_identifier(exception: BaseException) -> str:
    exception_class = type(exception)
    try:
        module = type.__getattribute__(exception_class, "__module__")
        qualname = type.__getattribute__(exception_class, "__qualname__")
    except BaseException:
        return _UNKNOWN_EXCEPTION
    if not _is_identifier(module) or not _is_identifier(qualname):
        return _UNKNOWN_EXCEPTION
    identifier = f"{module}.{qualname}"
    return identifier if len(identifier) <= _MAX_IDENTIFIER_LENGTH else _UNKNOWN_EXCEPTION


def _exception_attribute(exception: BaseException, name: str, default: object) -> object:
    try:
        return object.__getattribute__(exception, name)
    except BaseException:
        return default


def _traceback_shape(exception: BaseException, remaining: int) -> tuple[int, bool]:
    traceback = _exception_attribute(exception, "__traceback__", None)
    frames = 0
    seen: set[int] = set()
    while isinstance(traceback, types.TracebackType) and frames < remaining:
        identity = id(traceback)
        if identity in seen:
            return frames, True
        seen.add(identity)
        frames += 1
        traceback = traceback.tb_next
    return frames, traceback is not None


def _append_link(
    pending: list[tuple[BaseException, int]],
    linked: object,
    *,
    depth: int,
) -> bool:
    if not isinstance(linked, BaseException):
        return False
    if depth >= _MAX_EXCEPTION_DEPTH:
        return True
    pending.append((linked, depth + 1))
    return False


def build_exception_diagnostic_event(
    exception: BaseException,
    *,
    operation: DiagnosticOperation,
) -> ExceptionDiagnosticEvent:
    """Build a structural exception event without reading exception payload text."""
    if type(operation) is not DiagnosticOperation:
        raise DiagnosticEventValidationError("unsupported diagnostic operation")
    if not isinstance(exception, BaseException):
        return ExceptionDiagnosticEvent(
            operation=operation,
            exception_type=_UNKNOWN_EXCEPTION,
            has_traceback=False,
            traceback_frames=0,
            cause_count=0,
            context_count=0,
            group_count=0,
            group_member_count=0,
            structure_truncated=False,
        )

    pending = [(exception, 0)]
    seen: set[int] = set()
    traceback_frames = 0
    cause_count = 0
    context_count = 0
    group_count = 0
    group_member_count = 0
    truncated = False

    while pending:
        if len(seen) >= _MAX_EXCEPTION_NODES:
            truncated = True
            break
        current, depth = pending.pop()
        identity = id(current)
        if identity in seen:
            truncated = True
            continue
        seen.add(identity)

        frames, traceback_truncated = _traceback_shape(
            current,
            _MAX_TRACEBACK_FRAMES - traceback_frames,
        )
        traceback_frames += frames
        truncated = truncated or traceback_truncated

        cause = _exception_attribute(current, "__cause__", None)
        context = _exception_attribute(current, "__context__", None)
        suppressed = _exception_attribute(current, "__suppress_context__", False) is True
        if isinstance(cause, BaseException):
            cause_count = min(_MAX_EXCEPTION_NODES, cause_count + 1)
            truncated = _append_link(pending, cause, depth=depth) or truncated
        elif not suppressed and isinstance(context, BaseException):
            context_count = min(_MAX_EXCEPTION_NODES, context_count + 1)
            truncated = _append_link(pending, context, depth=depth) or truncated

        if isinstance(current, BaseExceptionGroup):
            group_count = min(_MAX_EXCEPTION_NODES, group_count + 1)
            children = _exception_attribute(current, "exceptions", ())
            if type(children) is not tuple:
                truncated = True
                continue
            remaining = _MAX_EXCEPTION_NODES - group_member_count
            accepted = children[:remaining]
            group_member_count += len(accepted)
            truncated = truncated or len(accepted) != len(children)
            for child in accepted:
                if not isinstance(child, BaseException):
                    truncated = True
                elif depth >= _MAX_EXCEPTION_DEPTH:
                    truncated = True
                else:
                    pending.append((child, depth + 1))

    return ExceptionDiagnosticEvent(
        operation=operation,
        exception_type=_exception_identifier(exception),
        has_traceback=traceback_frames > 0,
        traceback_frames=traceback_frames,
        cause_count=cause_count,
        context_count=context_count,
        group_count=group_count,
        group_member_count=group_member_count,
        structure_truncated=truncated,
    )


def _bounded_integer(value: object, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _uuid_hex(value: object) -> str:
    if type(value) is not uuid.UUID:
        raise DiagnosticEventValidationError("invalid correlation identifier")
    try:
        encoded = value.hex
    except BaseException:
        raise DiagnosticEventValidationError("invalid correlation identifier") from None
    if len(encoded) != 32 or any(character not in "0123456789abcdef" for character in encoded):
        raise DiagnosticEventValidationError("invalid correlation identifier")
    return encoded


def _exception_payload(event: ExceptionDiagnosticEvent) -> dict[str, object]:
    try:
        operation = event.operation
        exception_type = event.exception_type
        correlation_id = event.correlation_id
        has_traceback = event.has_traceback
        traceback_frames = event.traceback_frames
        cause_count = event.cause_count
        context_count = event.context_count
        group_count = event.group_count
        group_member_count = event.group_member_count
        structure_truncated = event.structure_truncated
    except BaseException:
        raise DiagnosticEventValidationError("malformed exception event") from None

    if type(operation) is not DiagnosticOperation:
        raise DiagnosticEventValidationError("invalid diagnostic operation")
    if type(exception_type) is not str or (
        exception_type != _UNKNOWN_EXCEPTION and not _is_identifier(exception_type)
    ):
        raise DiagnosticEventValidationError("invalid exception identifier")
    if type(has_traceback) is not bool or type(structure_truncated) is not bool:
        raise DiagnosticEventValidationError("invalid diagnostic boolean")
    bounds = (
        (traceback_frames, _MAX_TRACEBACK_FRAMES),
        (cause_count, _MAX_EXCEPTION_NODES),
        (context_count, _MAX_EXCEPTION_NODES),
        (group_count, _MAX_EXCEPTION_NODES),
        (group_member_count, _MAX_EXCEPTION_NODES),
    )
    if any(not _bounded_integer(value, maximum) for value, maximum in bounds):
        raise DiagnosticEventValidationError("invalid diagnostic count")

    return {
        "event_code": DiagnosticEventCode.EXCEPTION_DIAGNOSTIC.value,
        "operation": operation.value,
        "exception_type": exception_type,
        "correlation_id": _uuid_hex(correlation_id),
        "has_traceback": has_traceback,
        "traceback_frames": traceback_frames,
        "cause_count": cause_count,
        "context_count": context_count,
        "group_count": group_count,
        "group_member_count": group_member_count,
        "structure_truncated": structure_truncated,
    }


def _source_payload(event: DiagnosticEvent) -> dict[str, object]:
    try:
        source_class = event.source_class
    except BaseException:
        raise DiagnosticEventValidationError("malformed source event") from None
    if type(source_class) is not SourceClass:
        raise DiagnosticEventValidationError("invalid source class")
    code = (
        DiagnosticEventCode.LEGACY_LOG_SUPPRESSED
        if type(event) is LegacyLogSuppressedEvent
        else DiagnosticEventCode.INVALID_DIAGNOSTIC_EVENT
    )
    return {"event_code": code.value, "source_class": source_class.value}


def serialize_diagnostic_event(event: object) -> str:
    """Serialize one exact approved event without fallback string conversion."""
    if type(event) is ExceptionDiagnosticEvent:
        payload = _exception_payload(event)
    elif type(event) in (LegacyLogSuppressedEvent, InvalidDiagnosticEvent):
        payload = _source_payload(event)
    else:
        raise DiagnosticEventValidationError("unsupported diagnostic event")
    try:
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise DiagnosticEventValidationError("diagnostic serialization failed") from None
