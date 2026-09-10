"""Closed, bounded diagnostic events for Metroliza-managed log sinks."""

from __future__ import annotations

import json
import re
import types
import uuid
from dataclasses import dataclass, field
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
    RUNTIME_PROVENANCE = "runtime_provenance"
    STARTUP_DIAGNOSTIC = "startup_diagnostic"


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


class StartupMode(str, Enum):
    UNKNOWN = "unknown"
    INTERACTIVE = "interactive"
    STARTUP_SMOKE = "startup_smoke"
    PDF_SMOKE = "pdf_smoke"
    UI_SMOKE = "ui_smoke"


class StartupCallsite(str, Enum):
    BOOTSTRAP = "bootstrap"
    LOGGING_INITIALIZE = "logging_initialize"
    LOGGING_READY = "logging_ready"
    CONFIG_LOAD = "config_load"
    CONFIG_READY = "config_ready"
    QAPPLICATION_REQUEST = "qapplication_request"
    QAPPLICATION_READY = "qapplication_ready"
    LICENSE_CHECK = "license_check"
    LICENSE_REJECTED = "license_rejected"
    MAIN_WINDOW_FACTORY = "main_window_factory"
    MAIN_WINDOW_CONSTRUCT = "main_window_construct"
    MAIN_WINDOW_SHOW_REQUEST = "main_window_show_request"
    MAIN_WINDOW_SHOW_RETURNED = "main_window_show_returned"
    EVENT_LOOP_EXEC_REQUEST = "event_loop_exec_request"
    SMOKE_WORK = "smoke_work"
    SMOKE_RETURN = "smoke_return"
    APPLICATION_RETURN = "application_return"


class StartupOutcome(str, Enum):
    INVOCATION_STARTED = "invocation_started"
    MILESTONE = "milestone"
    STARTUP_COMPLETED = "startup_completed"
    STARTUP_REJECTED = "startup_rejected"
    STARTUP_FAILED = "startup_failed"
    APPLICATION_RETURNED = "application_returned"
    APPLICATION_FAILED = "application_failed"


class RuntimeMode(str, Enum):
    UNKNOWN = "unknown"
    SOURCE = "source"
    FROZEN = "frozen"


class BuildPackager(str, Enum):
    UNKNOWN = "unknown"
    SOURCE = "source"
    PYINSTALLER = "pyinstaller"
    NUITKA = "nuitka"


_STARTUPMODE_LITERALS = (
    (StartupMode.UNKNOWN, "unknown"),
    (StartupMode.INTERACTIVE, "interactive"),
    (StartupMode.STARTUP_SMOKE, "startup_smoke"),
    (StartupMode.PDF_SMOKE, "pdf_smoke"),
    (StartupMode.UI_SMOKE, "ui_smoke"),
)

_STARTUPCALLSITE_LITERALS = (
    (StartupCallsite.BOOTSTRAP, "bootstrap"),
    (StartupCallsite.LOGGING_INITIALIZE, "logging_initialize"),
    (StartupCallsite.LOGGING_READY, "logging_ready"),
    (StartupCallsite.CONFIG_LOAD, "config_load"),
    (StartupCallsite.CONFIG_READY, "config_ready"),
    (StartupCallsite.QAPPLICATION_REQUEST, "qapplication_request"),
    (StartupCallsite.QAPPLICATION_READY, "qapplication_ready"),
    (StartupCallsite.LICENSE_CHECK, "license_check"),
    (StartupCallsite.LICENSE_REJECTED, "license_rejected"),
    (StartupCallsite.MAIN_WINDOW_FACTORY, "main_window_factory"),
    (StartupCallsite.MAIN_WINDOW_CONSTRUCT, "main_window_construct"),
    (StartupCallsite.MAIN_WINDOW_SHOW_REQUEST, "main_window_show_request"),
    (StartupCallsite.MAIN_WINDOW_SHOW_RETURNED, "main_window_show_returned"),
    (StartupCallsite.EVENT_LOOP_EXEC_REQUEST, "event_loop_exec_request"),
    (StartupCallsite.SMOKE_WORK, "smoke_work"),
    (StartupCallsite.SMOKE_RETURN, "smoke_return"),
    (StartupCallsite.APPLICATION_RETURN, "application_return"),
)

_STARTUPOUTCOME_LITERALS = (
    (StartupOutcome.INVOCATION_STARTED, "invocation_started"),
    (StartupOutcome.MILESTONE, "milestone"),
    (StartupOutcome.STARTUP_COMPLETED, "startup_completed"),
    (StartupOutcome.STARTUP_REJECTED, "startup_rejected"),
    (StartupOutcome.STARTUP_FAILED, "startup_failed"),
    (StartupOutcome.APPLICATION_RETURNED, "application_returned"),
    (StartupOutcome.APPLICATION_FAILED, "application_failed"),
)

_RUNTIMEMODE_LITERALS = (
    (RuntimeMode.UNKNOWN, "unknown"),
    (RuntimeMode.SOURCE, "source"),
    (RuntimeMode.FROZEN, "frozen"),
)

_BUILDPACKAGER_LITERALS = (
    (BuildPackager.UNKNOWN, "unknown"),
    (BuildPackager.SOURCE, "source"),
    (BuildPackager.PYINSTALLER, "pyinstaller"),
    (BuildPackager.NUITKA, "nuitka"),
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
    (DiagnosticEventCode.RUNTIME_PROVENANCE, "runtime_provenance"),
    (DiagnosticEventCode.STARTUP_DIAGNOSTIC, "startup_diagnostic"),
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


@dataclass(frozen=True, slots=True)
class RuntimeProvenanceEvent:
    """Closed build facts; release identity comes only from reviewed source."""

    invocation_id: uuid.UUID
    startup_id: uuid.UUID
    sequence: int
    runtime: RuntimeMode
    packager: BuildPackager
    git_sha: str = "unknown"
    dirty: bool | None = None
    release_year: int = field(kw_only=True)
    release_month: int = field(kw_only=True)
    release_candidate: int | None = field(kw_only=True)

    def __post_init__(self) -> None:
        _provenance_payload(self)


@dataclass(frozen=True, slots=True)
class StartupDiagnosticEvent:
    """One observed bootstrap boundary, never an arbitrary log or traceback."""

    invocation_id: uuid.UUID
    startup_id: uuid.UUID
    sequence: int
    mode: StartupMode
    callsite: StartupCallsite
    outcome: StartupOutcome
    exit_code: int | None = None
    exception: ExceptionDiagnosticEvent | None = None

    def __post_init__(self) -> None:
        _startup_payload(self)


DiagnosticEvent = (
    LegacyLogSuppressedEvent | InvalidDiagnosticEvent | ExceptionDiagnosticEvent
    | RuntimeProvenanceEvent | StartupDiagnosticEvent
)


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


def _startup_identity(event: RuntimeProvenanceEvent | StartupDiagnosticEvent) -> dict[str, object]:
    invocation_id = _uuid_hex(event.invocation_id)
    startup_id = _uuid_hex(event.startup_id)
    for identifier in (invocation_id, startup_id):
        if identifier[12] != "4" or identifier[16] not in "89ab":
            raise DiagnosticEventValidationError("invalid generated identifier")
    if invocation_id == startup_id:
        raise DiagnosticEventValidationError("startup identifiers must be distinct")
    if not _bounded_integer(event.sequence, 16) or event.sequence == 0:
        raise DiagnosticEventValidationError("invalid startup sequence")
    return {"invocation_id": invocation_id, "startup_id": startup_id, "sequence": event.sequence}


def _validated_build_facts(event: RuntimeProvenanceEvent) -> None:
    sha = event.git_sha
    if type(sha) is not str or len(sha) not in (7, 40, 64):
        raise DiagnosticEventValidationError("invalid build identity")
    if sha != "unknown" and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha) is None:
        raise DiagnosticEventValidationError("invalid build identity")
    if event.dirty is not None and type(event.dirty) is not bool:
        raise DiagnosticEventValidationError("invalid build dirty state")
    if event.packager is BuildPackager.SOURCE:
        valid = event.runtime is RuntimeMode.SOURCE and sha == "unknown" and event.dirty is None
    elif event.packager is BuildPackager.UNKNOWN:
        valid = sha == "unknown" and event.dirty is None
    else:
        valid = event.runtime is RuntimeMode.FROZEN and sha != "unknown" and type(event.dirty) is bool
    if not valid:
        raise DiagnosticEventValidationError("inconsistent build identity")


def _release_version(event: RuntimeProvenanceEvent) -> str:
    if not _bounded_integer(event.release_year, 9999) or event.release_year < 2000:
        raise DiagnosticEventValidationError("invalid release year")
    if not _bounded_integer(event.release_month, 12) or event.release_month == 0:
        raise DiagnosticEventValidationError("invalid release month")
    candidate = event.release_candidate
    if candidate is not None and (not _bounded_integer(candidate, 999) or candidate == 0):
        raise DiagnosticEventValidationError("invalid release candidate")
    version = f"{event.release_year:04d}.{event.release_month:02d}"
    return version if candidate is None else f"{version}rc{candidate}"


def _provenance_payload(event: RuntimeProvenanceEvent) -> dict[str, object]:
    runtime = _canonical_literal(event.runtime, _RUNTIMEMODE_LITERALS, "invalid runtime")
    packager = _canonical_literal(event.packager, _BUILDPACKAGER_LITERALS, "invalid packager")
    _validated_build_facts(event)
    return {
        "event_code": _event_code_literal(DiagnosticEventCode.RUNTIME_PROVENANCE),
        **_startup_identity(event),
        "release_version": _release_version(event),
        "git_sha": event.git_sha,
        "runtime": runtime,
        "packager": packager,
        "dirty": event.dirty,
    }


def _startup_exception(event: StartupDiagnosticEvent) -> dict[str, object] | None:
    failed = event.outcome is StartupOutcome.STARTUP_FAILED or event.outcome is StartupOutcome.APPLICATION_FAILED
    if event.exception is None:
        if failed:
            raise DiagnosticEventValidationError("missing failure shape")
        return None
    if not failed or type(event.exception) is not ExceptionDiagnosticEvent:
        raise DiagnosticEventValidationError("invalid startup exception")
    payload = _exception_payload(event.exception)
    for key in ("event_code", "operation", "correlation_id"):
        payload.pop(key)
    return payload


def _validate_startup_terminal(event: StartupDiagnosticEvent) -> None:
    if event.outcome is StartupOutcome.STARTUP_COMPLETED:
        valid = (
            event.callsite is StartupCallsite.EVENT_LOOP_EXEC_REQUEST and event.exit_code is None
        ) or (event.callsite is StartupCallsite.SMOKE_RETURN and event.exit_code == 0)
    elif event.outcome is StartupOutcome.STARTUP_REJECTED:
        valid = event.callsite in (StartupCallsite.LICENSE_REJECTED, StartupCallsite.SMOKE_RETURN)
        valid = valid and event.exit_code is not None and event.exit_code != 0
    elif event.outcome is StartupOutcome.APPLICATION_RETURNED:
        valid = event.callsite is StartupCallsite.APPLICATION_RETURN
    elif event.outcome is StartupOutcome.INVOCATION_STARTED:
        valid = event.callsite is StartupCallsite.BOOTSTRAP and event.exit_code is None
    else:
        valid = event.exit_code is None
    if not valid:
        raise DiagnosticEventValidationError("inconsistent startup outcome")


def _validate_startup_route(event: StartupDiagnosticEvent) -> None:
    ui_callsites = (
        StartupCallsite.LICENSE_CHECK, StartupCallsite.LICENSE_REJECTED,
        StartupCallsite.MAIN_WINDOW_FACTORY, StartupCallsite.MAIN_WINDOW_CONSTRUCT,
        StartupCallsite.MAIN_WINDOW_SHOW_REQUEST, StartupCallsite.MAIN_WINDOW_SHOW_RETURNED,
        StartupCallsite.EVENT_LOOP_EXEC_REQUEST,
    )
    if event.callsite in ui_callsites and event.mode not in (StartupMode.INTERACTIVE, StartupMode.UI_SMOKE):
        raise DiagnosticEventValidationError("invalid UI startup route")
    if event.callsite in (StartupCallsite.SMOKE_WORK, StartupCallsite.SMOKE_RETURN):
        if event.mode not in (StartupMode.STARTUP_SMOKE, StartupMode.PDF_SMOKE):
            raise DiagnosticEventValidationError("invalid smoke startup route")
    if event.outcome is StartupOutcome.APPLICATION_FAILED:
        if event.callsite is not StartupCallsite.EVENT_LOOP_EXEC_REQUEST:
            raise DiagnosticEventValidationError("application failure before startup boundary")
    if event.outcome is StartupOutcome.STARTUP_FAILED:
        if event.callsite in (StartupCallsite.EVENT_LOOP_EXEC_REQUEST, StartupCallsite.APPLICATION_RETURN):
            raise DiagnosticEventValidationError("startup failure after startup boundary")


def _validate_startup_mode(event: StartupDiagnosticEvent) -> None:
    early = (
        StartupCallsite.BOOTSTRAP, StartupCallsite.LOGGING_INITIALIZE,
        StartupCallsite.LOGGING_READY, StartupCallsite.CONFIG_LOAD,
    )
    if event.callsite in early and event.mode is not StartupMode.UNKNOWN:
        raise DiagnosticEventValidationError("mode before configuration")
    if event.callsite is StartupCallsite.CONFIG_READY and event.mode is StartupMode.UNKNOWN:
        raise DiagnosticEventValidationError("missing configured mode")
    if event.callsite in (StartupCallsite.QAPPLICATION_REQUEST, StartupCallsite.QAPPLICATION_READY):
        if event.mode not in (StartupMode.INTERACTIVE, StartupMode.UI_SMOKE, StartupMode.STARTUP_SMOKE):
            raise DiagnosticEventValidationError("invalid QApplication route")


def _startup_payload(event: StartupDiagnosticEvent) -> dict[str, object]:
    mode = _canonical_literal(event.mode, _STARTUPMODE_LITERALS, "invalid startup mode")
    callsite = _canonical_literal(event.callsite, _STARTUPCALLSITE_LITERALS, "invalid startup callsite")
    outcome = _canonical_literal(event.outcome, _STARTUPOUTCOME_LITERALS, "invalid startup outcome")
    if event.exit_code is not None and (
        type(event.exit_code) is not int or not -(2**31) <= event.exit_code <= 2**32 - 1
    ):
        raise DiagnosticEventValidationError("invalid observed return code")
    _validate_startup_terminal(event)
    _validate_startup_route(event)
    _validate_startup_mode(event)
    return {
        "event_code": _event_code_literal(DiagnosticEventCode.STARTUP_DIAGNOSTIC),
        **_startup_identity(event),
        "mode": mode,
        "callsite": callsite,
        "outcome": outcome,
        "exit_code": event.exit_code,
        "exception": _startup_exception(event),
    }


def serialize_diagnostic_event(event: object) -> str:
    """Serialize one exact approved event without fallback string conversion."""
    try:
        if type(event) is ExceptionDiagnosticEvent:
            payload = _exception_payload(event)
        elif type(event) is LegacyLogSuppressedEvent or type(event) is InvalidDiagnosticEvent:
            payload = _source_payload(event)
        elif type(event) is RuntimeProvenanceEvent:
            payload = _provenance_payload(event)
        elif type(event) is StartupDiagnosticEvent:
            payload = _startup_payload(event)
        else:
            raise DiagnosticEventValidationError("unsupported diagnostic event")
        output = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        if len(output) > 4096:
            raise DiagnosticEventValidationError("diagnostic event too large")
        return output
    except DiagnosticEventValidationError:
        raise
    except (AttributeError, TypeError, ValueError):
        raise DiagnosticEventValidationError("diagnostic serialization failed") from None
