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
_UNKNOWN_EXCEPTION = "unknown_exception"

_BASE_EXCEPTION_TRACEBACK_DESCRIPTOR = BaseException.__dict__.get("__traceback__")
_BASE_EXCEPTION_CAUSE_DESCRIPTOR = BaseException.__dict__.get("__cause__")
_BASE_EXCEPTION_CONTEXT_DESCRIPTOR = BaseException.__dict__.get("__context__")
_BASE_EXCEPTION_SUPPRESSION_DESCRIPTOR = BaseException.__dict__.get("__suppress_context__")
_BASE_EXCEPTION_GROUP_EXCEPTIONS_DESCRIPTOR = BaseExceptionGroup.__dict__.get("exceptions")
_UUID_INT_DESCRIPTOR = uuid.UUID.__dict__.get("int")
_SAFE_EXCEPTION_DESCRIPTOR_TYPES = (types.GetSetDescriptorType, types.MemberDescriptorType)


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


class ExceptionKind(str, Enum):
    """Closed exception identities approved for persistent diagnostics."""

    UNKNOWN_EXCEPTION = _UNKNOWN_EXCEPTION
    BASE_EXCEPTION_GROUP = "base_exception_group"
    EXCEPTION_GROUP = "exception_group"
    IMPORT_ERROR = "import_error"
    KEY_ERROR = "key_error"
    OS_ERROR = "os_error"
    RUNTIME_ERROR = "runtime_error"
    TYPE_ERROR = "type_error"
    VALUE_ERROR = "value_error"


_KNOWN_EXCEPTION_KINDS = (
    (BaseExceptionGroup, ExceptionKind.BASE_EXCEPTION_GROUP),
    (ExceptionGroup, ExceptionKind.EXCEPTION_GROUP),
    (ImportError, ExceptionKind.IMPORT_ERROR),
    (KeyError, ExceptionKind.KEY_ERROR),
    (OSError, ExceptionKind.OS_ERROR),
    (RuntimeError, ExceptionKind.RUNTIME_ERROR),
    (TypeError, ExceptionKind.TYPE_ERROR),
    (ValueError, ExceptionKind.VALUE_ERROR),
)
_LEGACY_EXCEPTION_TYPES = (
    (ExceptionKind.BASE_EXCEPTION_GROUP, "builtins.BaseExceptionGroup"),
    (ExceptionKind.EXCEPTION_GROUP, "builtins.ExceptionGroup"),
    (ExceptionKind.IMPORT_ERROR, "builtins.ImportError"),
    (ExceptionKind.KEY_ERROR, "builtins.KeyError"),
    (ExceptionKind.OS_ERROR, "builtins.OSError"),
    (ExceptionKind.RUNTIME_ERROR, "builtins.RuntimeError"),
    (ExceptionKind.TYPE_ERROR, "builtins.TypeError"),
    (ExceptionKind.VALUE_ERROR, "builtins.ValueError"),
)


class SourceClass(str, Enum):
    """Coarse, non-identifying source classes for suppressed legacy logs."""

    APPLICATION = "application"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


_DIAGNOSTIC_EVENT_CODE_LITERALS = (
    (DiagnosticEventCode.LEGACY_LOG_SUPPRESSED, "legacy_log_suppressed"),
    (DiagnosticEventCode.INVALID_DIAGNOSTIC_EVENT, "invalid_diagnostic_event"),
    (DiagnosticEventCode.EXCEPTION_DIAGNOSTIC, "exception_diagnostic"),
)
_DIAGNOSTIC_OPERATION_LITERALS = (
    (DiagnosticOperation.UNHANDLED_EXCEPTION, "unhandled_exception"),
    (DiagnosticOperation.QT_DIALOG_IMPORT_FAILURE, "qt_dialog_import_failure"),
)
_EXCEPTION_KIND_LITERALS = (
    (ExceptionKind.UNKNOWN_EXCEPTION, "unknown_exception"),
    (ExceptionKind.BASE_EXCEPTION_GROUP, "base_exception_group"),
    (ExceptionKind.EXCEPTION_GROUP, "exception_group"),
    (ExceptionKind.IMPORT_ERROR, "import_error"),
    (ExceptionKind.KEY_ERROR, "key_error"),
    (ExceptionKind.OS_ERROR, "os_error"),
    (ExceptionKind.RUNTIME_ERROR, "runtime_error"),
    (ExceptionKind.TYPE_ERROR, "type_error"),
    (ExceptionKind.VALUE_ERROR, "value_error"),
)
_SOURCE_CLASS_LITERALS = (
    (SourceClass.APPLICATION, "application"),
    (SourceClass.EXTERNAL, "external"),
    (SourceClass.UNKNOWN, "unknown"),
)


def _canonical_literal(
    value: object,
    approved: tuple[tuple[object, str], ...],
    error_message: str,
) -> str:
    for member, literal in approved:
        if value is member:
            return literal
    raise DiagnosticEventValidationError(error_message)


def _event_code_literal(value: object) -> str:
    return _canonical_literal(
        value,
        _DIAGNOSTIC_EVENT_CODE_LITERALS,
        "unsupported diagnostic event code",
    )


def _operation_literal(value: object) -> str:
    return _canonical_literal(
        value,
        _DIAGNOSTIC_OPERATION_LITERALS,
        "unsupported diagnostic operation",
    )


def _exception_kind_literal(value: object) -> str:
    return _canonical_literal(
        value,
        _EXCEPTION_KIND_LITERALS,
        "unsupported exception kind",
    )


def _source_class_literal(value: object) -> str:
    return _canonical_literal(
        value,
        _SOURCE_CLASS_LITERALS,
        "unsupported source class",
    )


@dataclass(frozen=True, slots=True, init=False)
class LegacyLogSuppressedEvent:
    """Fixed event emitted instead of an arbitrary legacy log payload."""

    source_class: SourceClass

    def __init__(self, source_class: SourceClass) -> None:
        _source_class_literal(source_class)
        object.__setattr__(self, "source_class", source_class)


@dataclass(frozen=True, slots=True, init=False)
class InvalidDiagnosticEvent:
    """Fixed event emitted when a typed event fails validation."""

    source_class: SourceClass

    def __init__(self, source_class: SourceClass) -> None:
        _source_class_literal(source_class)
        object.__setattr__(self, "source_class", source_class)


@dataclass(frozen=True, slots=True, init=False)
class ExceptionDiagnosticEvent:
    """Bounded exception type and shape without exception-controlled text."""

    operation: DiagnosticOperation
    exception_kind: ExceptionKind
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
        exception_kind: ExceptionKind,
        has_traceback: bool,
        traceback_frames: int,
        cause_count: int,
        context_count: int,
        group_count: int,
        group_member_count: int,
        structure_truncated: bool,
    ) -> None:
        _operation_literal(operation)
        _exception_kind_literal(exception_kind)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "exception_kind", exception_kind)
        object.__setattr__(self, "correlation_id", uuid.uuid4())
        object.__setattr__(self, "has_traceback", has_traceback)
        object.__setattr__(self, "traceback_frames", traceback_frames)
        object.__setattr__(self, "cause_count", cause_count)
        object.__setattr__(self, "context_count", context_count)
        object.__setattr__(self, "group_count", group_count)
        object.__setattr__(self, "group_member_count", group_member_count)
        object.__setattr__(self, "structure_truncated", structure_truncated)

    @property
    def exception_type(self) -> str:
        """Return the former source-controlled identifier for in-process compatibility."""
        for kind, identifier in _LEGACY_EXCEPTION_TYPES:
            if self.exception_kind is kind:
                return identifier
        return _UNKNOWN_EXCEPTION


DiagnosticEvent = LegacyLogSuppressedEvent | InvalidDiagnosticEvent | ExceptionDiagnosticEvent


def _exception_kind(exception: BaseException) -> ExceptionKind:
    exception_class = type(exception)
    for known_class, kind in _KNOWN_EXCEPTION_KINDS:
        if exception_class is known_class:
            return kind
    return ExceptionKind.UNKNOWN_EXCEPTION


def _base_exception_slot(
    exception: BaseException,
    descriptor: object,
    owner: type[BaseException],
) -> tuple[object, bool]:
    if type(descriptor) not in _SAFE_EXCEPTION_DESCRIPTOR_TYPES:
        return None, False
    try:
        return descriptor.__get__(exception, owner), True
    except BaseException:
        return None, False


def _traceback_shape(exception: BaseException, remaining: int) -> tuple[int, bool]:
    traceback, available = _base_exception_slot(
        exception,
        _BASE_EXCEPTION_TRACEBACK_DESCRIPTOR,
        BaseException,
    )
    if not available:
        return 0, True
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


def _linked_exception_shape(
    exception: BaseException,
    *,
    depth: int,
) -> tuple[list[tuple[BaseException, int]], int, int, bool]:
    cause, cause_available = _base_exception_slot(
        exception,
        _BASE_EXCEPTION_CAUSE_DESCRIPTOR,
        BaseException,
    )
    context, context_available = _base_exception_slot(
        exception,
        _BASE_EXCEPTION_CONTEXT_DESCRIPTOR,
        BaseException,
    )
    suppressed, suppression_available = _base_exception_slot(
        exception,
        _BASE_EXCEPTION_SUPPRESSION_DESCRIPTOR,
        BaseException,
    )
    linked: list[tuple[BaseException, int]] = []
    if not (cause_available and context_available and suppression_available):
        return linked, 0, 0, True
    if isinstance(cause, BaseException):
        truncated = _append_link(linked, cause, depth=depth)
        return linked, 1, 0, truncated
    if not suppressed and isinstance(context, BaseException):
        truncated = _append_link(linked, context, depth=depth)
        return linked, 0, 1, truncated
    return linked, 0, 0, False


def _exception_group_shape(
    exception: BaseException,
    *,
    depth: int,
    remaining_members: int,
) -> tuple[list[tuple[BaseException, int]], int, int, bool]:
    if not isinstance(exception, BaseExceptionGroup):
        return [], 0, 0, False
    children, available = _base_exception_slot(
        exception,
        _BASE_EXCEPTION_GROUP_EXCEPTIONS_DESCRIPTOR,
        BaseExceptionGroup,
    )
    if not available:
        return [], 0, 0, True
    if type(children) is not tuple:
        return [], 0, 0, True
    accepted = children[:remaining_members]
    pending: list[tuple[BaseException, int]] = []
    truncated = len(accepted) != len(children)
    for child in accepted:
        if not isinstance(child, BaseException) or depth >= _MAX_EXCEPTION_DEPTH:
            truncated = True
        else:
            pending.append((child, depth + 1))
    return pending, 1, len(accepted), truncated


def build_exception_diagnostic_event(
    exception: BaseException,
    *,
    operation: DiagnosticOperation,
) -> ExceptionDiagnosticEvent:
    """Build a structural exception event without reading exception payload text."""
    _operation_literal(operation)
    if not isinstance(exception, BaseException):
        return ExceptionDiagnosticEvent(
            operation=operation,
            exception_kind=ExceptionKind.UNKNOWN_EXCEPTION,
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

        linked, causes, contexts, linked_truncated = _linked_exception_shape(
            current,
            depth=depth,
        )
        pending.extend(linked)
        cause_count = min(_MAX_EXCEPTION_NODES, cause_count + causes)
        context_count = min(_MAX_EXCEPTION_NODES, context_count + contexts)
        truncated = truncated or linked_truncated

        children, groups, members, group_truncated = _exception_group_shape(
            current,
            depth=depth,
            remaining_members=_MAX_EXCEPTION_NODES - group_member_count,
        )
        pending.extend(children)
        group_count = min(_MAX_EXCEPTION_NODES, group_count + groups)
        group_member_count += members
        truncated = truncated or group_truncated

    return ExceptionDiagnosticEvent(
        operation=operation,
        exception_kind=_exception_kind(exception),
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
    if type(_UUID_INT_DESCRIPTOR) is not types.MemberDescriptorType:
        raise DiagnosticEventValidationError("invalid correlation identifier")
    try:
        integer = _UUID_INT_DESCRIPTOR.__get__(value, uuid.UUID)
    except BaseException:
        raise DiagnosticEventValidationError("invalid correlation identifier") from None
    if type(integer) is not int or integer < 0 or integer.bit_length() > 128:
        raise DiagnosticEventValidationError("invalid correlation identifier")
    return f"{integer:032x}"


def _exception_payload(event: ExceptionDiagnosticEvent) -> dict[str, object]:
    try:
        operation = event.operation
        exception_kind = event.exception_kind
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

    operation_literal = _operation_literal(operation)
    exception_kind_literal = _exception_kind_literal(exception_kind)
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
        "event_code": _event_code_literal(DiagnosticEventCode.EXCEPTION_DIAGNOSTIC),
        "operation": operation_literal,
        "exception_kind": exception_kind_literal,
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
    source_class_literal = _source_class_literal(source_class)
    code = (
        DiagnosticEventCode.LEGACY_LOG_SUPPRESSED
        if type(event) is LegacyLogSuppressedEvent
        else DiagnosticEventCode.INVALID_DIAGNOSTIC_EVENT
    )
    return {
        "event_code": _event_code_literal(code),
        "source_class": source_class_literal,
    }


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
