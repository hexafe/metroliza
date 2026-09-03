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


def test_closed_events_serialize_with_fixed_schema_and_key_order(monkeypatch):
    correlation_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr(diagnostic_events.uuid, "uuid4", lambda: correlation_id)

    event = ExceptionDiagnosticEvent(
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
        exception_type="builtins.RuntimeError",
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
        '"exception_type":"builtins.RuntimeError",'
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
    assert parsed["exception_type"] == "builtins.ExceptionGroup"
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
            exception_type="builtins.RuntimeError",
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


def test_invalid_dynamic_exception_identifier_becomes_unknown(monkeypatch):
    marker = f"generated-{uuid.uuid4().hex}"
    exception_type = type(f"Invalid-{marker}", (RuntimeError,), {})
    exception_type.__module__ = f"invalid-{marker}"
    event = build_exception_diagnostic_event(
        exception_type(marker),
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
    )

    output = serialize_diagnostic_event(event)
    if marker in output:
        pytest.fail("invalid dynamic exception identifier reached output")
    assert event.exception_type == "unknown_exception"


def test_structured_output_is_bounded_by_closed_field_limits():
    event = ExceptionDiagnosticEvent(
        operation=DiagnosticOperation.QT_DIALOG_IMPORT_FAILURE,
        exception_type=f"package.{'A' * 80}",
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
