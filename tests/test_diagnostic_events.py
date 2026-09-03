import json
import uuid

import pytest

from metroliza.shared import diagnostic_events
from metroliza.shared.diagnostic_events import (
    DiagnosticEventValidationError,
    DiagnosticOperation,
    ExceptionDiagnosticEvent,
    InvalidDiagnosticEvent,
    LegacyLogSuppressedEvent,
    SourceClass,
    build_exception_diagnostic_event,
    serialize_diagnostic_event,
)


def _forged_enum_member(enum_type, equal_value, marker):
    forged = str.__new__(enum_type, equal_value)
    object.__setattr__(forged, "_name_", marker)
    object.__setattr__(forged, "_value_", marker)
    return forged


def _exception_event_fields():
    return {
        "operation": DiagnosticOperation.UNHANDLED_EXCEPTION,
        "exception_kind": diagnostic_events.ExceptionKind.RUNTIME_ERROR,
        "has_traceback": False,
        "traceback_frames": 0,
        "cause_count": 0,
        "context_count": 0,
        "group_count": 0,
        "group_member_count": 0,
        "structure_truncated": False,
    }


def test_closed_events_serialize_with_fixed_schema_and_key_order(monkeypatch):
    correlation_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr(diagnostic_events.uuid, "uuid4", lambda: correlation_id)

    event = ExceptionDiagnosticEvent(
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
        exception_kind=diagnostic_events.ExceptionKind.RUNTIME_ERROR,
        has_traceback=False,
        traceback_frames=0,
        cause_count=0,
        context_count=0,
        group_count=0,
        group_member_count=0,
        structure_truncated=False,
    )

    assert serialize_diagnostic_event(event) == (
        '{"event_code":"exception_diagnostic",'
        '"operation":"unhandled_exception",'
        '"exception_kind":"runtime_error",'
        '"correlation_id":"12345678123456781234567812345678",'
        '"has_traceback":false,"traceback_frames":0,'
        '"cause_count":0,"context_count":0,"group_count":0,'
        '"group_member_count":0,"structure_truncated":false}'
    )
    assert serialize_diagnostic_event(
        LegacyLogSuppressedEvent(SourceClass.APPLICATION)
    ) == '{"event_code":"legacy_log_suppressed","source_class":"application"}'
    assert serialize_diagnostic_event(
        InvalidDiagnosticEvent(SourceClass.EXTERNAL)
    ) == '{"event_code":"invalid_diagnostic_event","source_class":"external"}'


def test_exception_builder_keeps_only_bounded_structure(monkeypatch):
    marker = f"generated-{uuid.uuid4().hex}"
    monkeypatch.setattr(
        diagnostic_events.uuid,
        "uuid4",
        lambda: uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    )

    try:
        try:
            raise ValueError(marker)
        except ValueError as cause:
            cause.add_note(marker)
            raise ExceptionGroup(marker, [RuntimeError(marker), KeyError(marker)]) from cause
    except ExceptionGroup as exception:
        event = build_exception_diagnostic_event(
            exception,
            operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
        )

    output = serialize_diagnostic_event(event)
    parsed = json.loads(output)
    if marker in output:
        pytest.fail("exception payload reached structured diagnostic output")
    assert parsed["exception_kind"] == "exception_group"
    assert parsed["has_traceback"] is True
    assert 1 <= parsed["traceback_frames"] <= 64
    assert parsed["cause_count"] == 1
    assert parsed["context_count"] == 0
    assert parsed["group_count"] == 1
    assert parsed["group_member_count"] == 2
    assert parsed["structure_truncated"] is False


def test_event_constructors_reject_unknown_fields():
    with pytest.raises(TypeError):
        LegacyLogSuppressedEvent(SourceClass.APPLICATION, metadata={"unknown": True})

    with pytest.raises(TypeError):
        ExceptionDiagnosticEvent(
            operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
            exception_kind=diagnostic_events.ExceptionKind.RUNTIME_ERROR,
            has_traceback=False,
            traceback_frames=0,
            cause_count=0,
            context_count=0,
            group_count=0,
            group_member_count=0,
            structure_truncated=False,
            payload="not allowed",
        )


def test_unsupported_values_fail_without_stringification():
    class HostileValue:
        def __str__(self):
            raise AssertionError("unsupported event value was stringified")

        def __repr__(self):
            raise AssertionError("unsupported event value was represented")

    event = LegacyLogSuppressedEvent(SourceClass.APPLICATION)
    object.__setattr__(event, "source_class", HostileValue())

    with pytest.raises(DiagnosticEventValidationError):
        serialize_diagnostic_event(event)


def test_malformed_and_unknown_event_instances_fail_closed():
    malformed = object.__new__(ExceptionDiagnosticEvent)

    with pytest.raises(DiagnosticEventValidationError):
        serialize_diagnostic_event(malformed)
    with pytest.raises(DiagnosticEventValidationError):
        serialize_diagnostic_event(object())


def test_dynamic_exception_identity_becomes_closed_unknown():
    marker = f"generated-{uuid.uuid4().hex}"
    exception_type = type(
        f"Dynamic_{marker}",
        (RuntimeError,),
        {"__module__": f"package_{marker}", "__qualname__": f"Dynamic_{marker}"},
    )
    event = build_exception_diagnostic_event(
        exception_type(marker),
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
    )

    output = serialize_diagnostic_event(event)
    if marker in output:
        pytest.fail("dynamic exception identity reached output")
    assert event.exception_kind is diagnostic_events.ExceptionKind.UNKNOWN_EXCEPTION


def test_exception_kind_rejects_caller_text_and_forgery_without_rendering():
    marker = f"generated-{uuid.uuid4().hex}"
    fields = {
        "operation": DiagnosticOperation.UNHANDLED_EXCEPTION,
        "has_traceback": False,
        "traceback_frames": 0,
        "cause_count": 0,
        "context_count": 0,
        "group_count": 0,
        "group_member_count": 0,
        "structure_truncated": False,
    }

    with pytest.raises(TypeError):
        ExceptionDiagnosticEvent(exception_type=marker, **fields)
    with pytest.raises(DiagnosticEventValidationError):
        ExceptionDiagnosticEvent(exception_kind=marker, **fields)

    event = ExceptionDiagnosticEvent(
        exception_kind=diagnostic_events.ExceptionKind.RUNTIME_ERROR,
        **fields,
    )

    class HostileKind:
        def __str__(self):
            raise AssertionError("forged kind was stringified")

        def __repr__(self):
            raise AssertionError("forged kind was represented")

    object.__setattr__(event, "exception_kind", HostileKind())
    with pytest.raises(DiagnosticEventValidationError):
        serialize_diagnostic_event(event)


def test_noncanonical_enum_instances_are_rejected_at_public_boundaries():
    marker = f"generated-{uuid.uuid4().hex}"
    operation = _forged_enum_member(
        DiagnosticOperation,
        DiagnosticOperation.UNHANDLED_EXCEPTION.value,
        marker,
    )
    exception_kind = _forged_enum_member(
        diagnostic_events.ExceptionKind,
        diagnostic_events.ExceptionKind.RUNTIME_ERROR.value,
        marker,
    )
    source_class = _forged_enum_member(
        SourceClass,
        SourceClass.APPLICATION.value,
        marker,
    )

    assert operation == DiagnosticOperation.UNHANDLED_EXCEPTION.value
    assert exception_kind == diagnostic_events.ExceptionKind.RUNTIME_ERROR.value
    assert source_class == SourceClass.APPLICATION.value

    fields = _exception_event_fields()
    with pytest.raises(DiagnosticEventValidationError):
        ExceptionDiagnosticEvent(**{**fields, "operation": operation})
    with pytest.raises(DiagnosticEventValidationError):
        build_exception_diagnostic_event(RuntimeError(marker), operation=operation)
    with pytest.raises(DiagnosticEventValidationError):
        ExceptionDiagnosticEvent(**{**fields, "exception_kind": exception_kind})
    with pytest.raises(DiagnosticEventValidationError):
        LegacyLogSuppressedEvent(source_class)
    with pytest.raises(DiagnosticEventValidationError):
        InvalidDiagnosticEvent(source_class)


def test_noncanonical_enum_mutations_fail_closed_during_serialization():
    marker = f"generated-{uuid.uuid4().hex}"
    operation = _forged_enum_member(
        DiagnosticOperation,
        DiagnosticOperation.UNHANDLED_EXCEPTION.value,
        marker,
    )
    exception_kind = _forged_enum_member(
        diagnostic_events.ExceptionKind,
        diagnostic_events.ExceptionKind.RUNTIME_ERROR.value,
        marker,
    )
    source_class = _forged_enum_member(
        SourceClass,
        SourceClass.APPLICATION.value,
        marker,
    )
    operation_event = ExceptionDiagnosticEvent(**_exception_event_fields())
    kind_event = ExceptionDiagnosticEvent(**_exception_event_fields())
    source_event = LegacyLogSuppressedEvent(SourceClass.APPLICATION)
    object.__setattr__(operation_event, "operation", operation)
    object.__setattr__(kind_event, "exception_kind", exception_kind)
    object.__setattr__(source_event, "source_class", source_class)

    for event in (operation_event, kind_event, source_event):
        with pytest.raises(DiagnosticEventValidationError):
            serialize_diagnostic_event(event)


def test_hostile_noncanonical_enum_internals_are_not_converted():
    class HostileValue:
        def __eq__(self, _other):
            raise AssertionError("forged enum value was compared")

        def __hash__(self):
            raise AssertionError("forged enum value was hashed")

        def __str__(self):
            raise AssertionError("forged enum value was stringified")

        def __repr__(self):
            raise AssertionError("forged enum value was represented")

    operation = str.__new__(DiagnosticOperation, "unhandled_exception")
    exception_kind = str.__new__(diagnostic_events.ExceptionKind, "runtime_error")
    source_class = str.__new__(SourceClass, "application")
    for forged in (operation, exception_kind, source_class):
        object.__setattr__(forged, "_name_", HostileValue())
        object.__setattr__(forged, "_value_", HostileValue())

    fields = _exception_event_fields()
    with pytest.raises(DiagnosticEventValidationError):
        ExceptionDiagnosticEvent(**{**fields, "operation": operation})
    with pytest.raises(DiagnosticEventValidationError):
        ExceptionDiagnosticEvent(**{**fields, "exception_kind": exception_kind})
    with pytest.raises(DiagnosticEventValidationError):
        LegacyLogSuppressedEvent(source_class)


def test_exception_kind_uses_only_exact_allowlisted_builtin_identity():
    exact = build_exception_diagnostic_event(
        RuntimeError("not persisted"),
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
    )

    class RuntimeErrorSubclass(RuntimeError):
        pass

    subclassed = build_exception_diagnostic_event(
        RuntimeErrorSubclass("not persisted"),
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
    )

    assert exact.exception_kind is diagnostic_events.ExceptionKind.RUNTIME_ERROR
    assert subclassed.exception_kind is diagnostic_events.ExceptionKind.UNKNOWN_EXCEPTION


def test_hostile_exception_metaclass_identity_hooks_are_not_invoked():
    marker = f"generated-{uuid.uuid4().hex}"
    invoked = []

    class HostileMeta(type):
        def __getattribute__(cls, name):
            if name in {"__module__", "__qualname__", "__name__"}:
                invoked.append(name)
                raise AssertionError("exception class metadata was read")
            return type.__getattribute__(cls, name)

        def __str__(cls):
            invoked.append("str")
            raise AssertionError("exception class was stringified")

        def __repr__(cls):
            invoked.append("repr")
            raise AssertionError("exception class was represented")

    exception_type = HostileMeta(
        f"Dynamic_{marker}",
        (RuntimeError,),
        {"__module__": f"package_{marker}", "__qualname__": f"Dynamic_{marker}"},
    )
    event = build_exception_diagnostic_event(
        exception_type(marker),
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
    )
    output = serialize_diagnostic_event(event)

    assert not invoked
    assert event.exception_kind is diagnostic_events.ExceptionKind.UNKNOWN_EXCEPTION
    if marker in output:
        pytest.fail("hostile exception class metadata reached output")


def test_exception_structure_uses_only_base_descriptors():
    marker = f"generated-{uuid.uuid4().hex}"
    invoked = []

    class HostileException(RuntimeError):
        @property
        def __traceback__(self):
            invoked.append("traceback")
            raise AssertionError("subclass traceback descriptor was invoked")

        @property
        def __cause__(self):
            invoked.append("cause")
            raise AssertionError("subclass cause descriptor was invoked")

        @property
        def __context__(self):
            invoked.append("context")
            raise AssertionError("subclass context descriptor was invoked")

        @property
        def __suppress_context__(self):
            invoked.append("suppress")
            raise AssertionError("subclass suppression descriptor was invoked")

    try:
        raise HostileException(marker)
    except HostileException as exception:
        event = build_exception_diagnostic_event(
            exception,
            operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
        )

    output = serialize_diagnostic_event(event)
    assert not invoked
    assert event.has_traceback is True
    if marker in output:
        pytest.fail("hostile exception payload reached output")


def test_exception_group_structure_uses_base_descriptor():
    marker = f"generated-{uuid.uuid4().hex}"
    invoked = []

    class HostileGroup(ExceptionGroup):
        @property
        def exceptions(self):
            invoked.append("exceptions")
            raise AssertionError("subclass group descriptor was invoked")

    event = build_exception_diagnostic_event(
        HostileGroup(marker, [RuntimeError(marker)]),
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
    )
    output = serialize_diagnostic_event(event)

    assert not invoked
    assert event.group_count == 1
    assert event.group_member_count == 1
    if marker in output:
        pytest.fail("hostile exception-group payload reached output")


def test_base_descriptor_access_failure_marks_structure_truncated(monkeypatch):
    marker = f"generated-{uuid.uuid4().hex}"
    monkeypatch.setattr(diagnostic_events, "_BASE_EXCEPTION_TRACEBACK_DESCRIPTOR", object())

    event = build_exception_diagnostic_event(
        RuntimeError(marker),
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
    )
    output = serialize_diagnostic_event(event)

    assert event.has_traceback is False
    assert event.traceback_frames == 0
    assert event.structure_truncated is True
    if marker in output:
        pytest.fail("exception payload reached truncated output")


def test_structured_output_is_bounded_by_closed_field_limits():
    event = ExceptionDiagnosticEvent(
        operation=DiagnosticOperation.QT_DIALOG_IMPORT_FAILURE,
        exception_kind=diagnostic_events.ExceptionKind.UNKNOWN_EXCEPTION,
        has_traceback=True,
        traceback_frames=64,
        cause_count=32,
        context_count=32,
        group_count=32,
        group_member_count=32,
        structure_truncated=True,
    )

    output = serialize_diagnostic_event(event)
    assert len(output) < 700
