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


def _exception_event_with_correlation(correlation_id):
    event = ExceptionDiagnosticEvent(**_exception_event_fields())
    object.__setattr__(event, "correlation_id", correlation_id)
    return event


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
        "unhandled_exception",
        marker,
    )
    exception_kind = _forged_enum_member(
        diagnostic_events.ExceptionKind,
        "runtime_error",
        marker,
    )
    source_class = _forged_enum_member(
        SourceClass,
        "application",
        marker,
    )

    assert operation == "unhandled_exception"
    assert exception_kind == "runtime_error"
    assert source_class == "application"

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
        "unhandled_exception",
        marker,
    )
    exception_kind = _forged_enum_member(
        diagnostic_events.ExceptionKind,
        "runtime_error",
        marker,
    )
    source_class = _forged_enum_member(
        SourceClass,
        "application",
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


def test_canonical_enum_internal_mutation_cannot_change_serialized_literals():
    marker = f"generated-{uuid.uuid4().hex}"
    operation_literals = (
        (DiagnosticOperation.UNHANDLED_EXCEPTION, "unhandled_exception"),
        (DiagnosticOperation.QT_DIALOG_IMPORT_FAILURE, "qt_dialog_import_failure"),
    )
    kind_literals = (
        (diagnostic_events.ExceptionKind.UNKNOWN_EXCEPTION, "unknown_exception"),
        (diagnostic_events.ExceptionKind.BASE_EXCEPTION_GROUP, "base_exception_group"),
        (diagnostic_events.ExceptionKind.EXCEPTION_GROUP, "exception_group"),
        (diagnostic_events.ExceptionKind.IMPORT_ERROR, "import_error"),
        (diagnostic_events.ExceptionKind.KEY_ERROR, "key_error"),
        (diagnostic_events.ExceptionKind.OS_ERROR, "os_error"),
        (diagnostic_events.ExceptionKind.RUNTIME_ERROR, "runtime_error"),
        (diagnostic_events.ExceptionKind.TYPE_ERROR, "type_error"),
        (diagnostic_events.ExceptionKind.VALUE_ERROR, "value_error"),
    )
    source_literals = (
        (SourceClass.APPLICATION, "application"),
        (SourceClass.EXTERNAL, "external"),
        (SourceClass.UNKNOWN, "unknown"),
    )
    code_members = (
        diagnostic_events.DiagnosticEventCode.LEGACY_LOG_SUPPRESSED,
        diagnostic_events.DiagnosticEventCode.INVALID_DIAGNOSTIC_EVENT,
        diagnostic_events.DiagnosticEventCode.EXCEPTION_DIAGNOSTIC,
    )
    members = code_members + tuple(member for member, _literal in operation_literals)
    members += tuple(member for member, _literal in kind_literals)
    members += tuple(member for member, _literal in source_literals)
    originals = tuple(
        (
            member,
            object.__getattribute__(member, "_name_"),
            object.__getattribute__(member, "_value_"),
        )
        for member in members
    )

    try:
        for member in members:
            object.__setattr__(member, "_name_", marker)
            object.__setattr__(member, "_value_", marker)

        outputs = []
        for operation, literal in operation_literals:
            event = ExceptionDiagnosticEvent(
                **{**_exception_event_fields(), "operation": operation}
            )
            output = serialize_diagnostic_event(event)
            outputs.append(output)
            if json.loads(output)["operation"] != literal:
                pytest.fail("canonical operation literal changed after enum mutation")
        for exception_kind, literal in kind_literals:
            event = ExceptionDiagnosticEvent(
                **{**_exception_event_fields(), "exception_kind": exception_kind}
            )
            output = serialize_diagnostic_event(event)
            outputs.append(output)
            if json.loads(output)["exception_kind"] != literal:
                pytest.fail("canonical exception-kind literal changed after enum mutation")
        for source_class, literal in source_literals:
            output = serialize_diagnostic_event(LegacyLogSuppressedEvent(source_class))
            outputs.append(output)
            if json.loads(output)["source_class"] != literal:
                pytest.fail("canonical source-class literal changed after enum mutation")

        code_outputs = (
            (
                serialize_diagnostic_event(LegacyLogSuppressedEvent(SourceClass.APPLICATION)),
                "legacy_log_suppressed",
            ),
            (
                serialize_diagnostic_event(InvalidDiagnosticEvent(SourceClass.APPLICATION)),
                "invalid_diagnostic_event",
            ),
            (
                serialize_diagnostic_event(ExceptionDiagnosticEvent(**_exception_event_fields())),
                "exception_diagnostic",
            ),
        )
        for output, literal in code_outputs:
            outputs.append(output)
            if json.loads(output)["event_code"] != literal:
                pytest.fail("canonical event-code literal changed after enum mutation")
        if any(marker in output for output in outputs):
            pytest.fail("mutated canonical enum internals reached serialized output")
    finally:
        for member, original_name, original_value in originals:
            object.__setattr__(member, "_name_", original_name)
            object.__setattr__(member, "_value_", original_value)

    for member, original_name, original_value in originals:
        if object.__getattribute__(member, "_name_") is not original_name:
            pytest.fail("canonical enum name was not restored")
        if object.__getattribute__(member, "_value_") is not original_value:
            pytest.fail("canonical enum value was not restored")
    baseline = serialize_diagnostic_event(
        _exception_event_with_correlation(uuid.UUID(int=0))
    )
    assert baseline == (
        '{"event_code":"exception_diagnostic",'
        '"operation":"unhandled_exception",'
        '"exception_kind":"runtime_error",'
        '"correlation_id":"00000000000000000000000000000000",'
        '"has_traceback":false,"traceback_frames":0,'
        '"cause_count":0,"context_count":0,"group_count":0,'
        '"group_member_count":0,"structure_truncated":false}'
    )


def test_serializer_never_reads_enum_value_or_name(monkeypatch):
    invoked = []

    def forbidden_enum_text(_member):
        invoked.append(True)
        raise AssertionError("enum text property was read")

    enum_types = (
        diagnostic_events.DiagnosticEventCode,
        DiagnosticOperation,
        diagnostic_events.ExceptionKind,
        SourceClass,
    )
    for enum_type in enum_types:
        monkeypatch.setattr(
            enum_type,
            "value",
            property(forbidden_enum_text),
            raising=False,
        )
        monkeypatch.setattr(
            enum_type,
            "name",
            property(forbidden_enum_text),
            raising=False,
        )

    outputs = (
        serialize_diagnostic_event(ExceptionDiagnosticEvent(**_exception_event_fields())),
        serialize_diagnostic_event(LegacyLogSuppressedEvent(SourceClass.APPLICATION)),
        serialize_diagnostic_event(InvalidDiagnosticEvent(SourceClass.UNKNOWN)),
    )

    if invoked:
        pytest.fail("serializer read mutable enum text properties")
    assert json.loads(outputs[0])["event_code"] == "exception_diagnostic"
    assert json.loads(outputs[1])["event_code"] == "legacy_log_suppressed"
    assert json.loads(outputs[2])["event_code"] == "invalid_diagnostic_event"


def test_oversized_uuid_is_rejected_before_hex_formatting(monkeypatch):
    marker = f"generated-{uuid.uuid4().hex}"
    correlation_id = uuid.UUID(int=0)
    object.__setattr__(correlation_id, "int", 1 << 200_000)
    invoked = []

    def forbidden_hex(_value):
        invoked.append(marker)
        raise AssertionError("UUID text conversion was invoked")

    monkeypatch.setattr(uuid.UUID, "hex", property(forbidden_hex))
    event = _exception_event_with_correlation(correlation_id)

    with pytest.raises(DiagnosticEventValidationError):
        serialize_diagnostic_event(event)
    if invoked:
        pytest.fail("oversized UUID reached hexadecimal formatting")


def test_invalid_uuid_integer_state_fails_without_conversion_hooks():
    marker = f"generated-{uuid.uuid4().hex}"
    invoked = []

    class HostileInteger:
        def __index__(self):
            invoked.append("index")
            raise AssertionError("UUID integer state was coerced")

        def __format__(self, _specification):
            invoked.append("format")
            raise AssertionError("UUID integer state was formatted")

        def __str__(self):
            invoked.append("str")
            raise AssertionError("UUID integer state was stringified")

        def __repr__(self):
            invoked.append("repr")
            raise AssertionError("UUID integer state was represented")

    invalid_states = (-1, True, HostileInteger())
    for invalid_state in invalid_states:
        correlation_id = uuid.UUID(int=0)
        object.__setattr__(correlation_id, "int", invalid_state)
        event = _exception_event_with_correlation(correlation_id)
        with pytest.raises(DiagnosticEventValidationError):
            serialize_diagnostic_event(event)

    malformed_id = uuid.UUID(int=0)
    object.__delattr__(malformed_id, "int")
    with pytest.raises(DiagnosticEventValidationError):
        serialize_diagnostic_event(_exception_event_with_correlation(malformed_id))
    if invoked:
        pytest.fail("invalid UUID state invoked a conversion hook")
    if marker in serialize_diagnostic_event(
        _exception_event_with_correlation(uuid.UUID(int=0))
    ):
        pytest.fail("generated marker reached valid UUID output")


def test_uuid_boundary_values_use_exact_lowercase_32_character_hex():
    cases = (
        (0, "0" * 32),
        ((1 << 128) - 1, "f" * 32),
    )
    for integer, expected in cases:
        output = serialize_diagnostic_event(
            _exception_event_with_correlation(uuid.UUID(int=integer))
        )
        encoded = json.loads(output)["correlation_id"]
        if encoded != expected:
            pytest.fail("bounded UUID did not use canonical hexadecimal encoding")


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
